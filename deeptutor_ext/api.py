"""前端点「运行」时调用的接口。

挂在 ``/api/v1/ext/notebook`` 下，接进宿主的 FastAPI 应用时不改宿主源码：站点钩子
等 ``deeptutor.api.main`` 加载完成后，拿到里面那个 app 对象再追加路由。

关于工作目录的校验：前端传来的块信息里带着执行时的工作目录，而这个值最终会交给内核
去 ``chdir``。所以这里必须把它限制在课程目录之内——那也正是内核容器唯一挂到的只读
目录，越界的路径在容器里本来就看不到，但拒绝在前面更清楚，也能挡住把别处的路径
写进书里的情况。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from deeptutor_ext.kernel import KernelUnavailable, get_session_manager
from deeptutor_ext.kernel import config as kernel_config

logger = logging.getLogger(__name__)

router = APIRouter()
course_router = APIRouter()


def _courses_root() -> Path:
    """课程目录。内核容器只挂了这一个目录，页面上能跑的代码都得在它下面。"""
    from deeptutor.services.path_service import get_path_service

    return (get_path_service().get_public_outputs_root() / "courses").resolve()


class RunCellRequest(BaseModel):
    book_id: str = Field(..., min_length=1)
    page_id: str = Field(..., min_length=1)
    block_id: str = Field(default="")
    # 学生可能改过代码，所以以前端传来的为准；留空则用书里存的那一份。
    code: str = Field(default="")
    cwd: str = Field(default="")
    timeout_s: int | None = None
    # 为真时，先把这一页里排在前面的可运行格子依次跑一遍，再跑这一格。
    # 学生跳着运行时会撞上「变量没定义」，这是给他们的一键补齐。
    through: bool = False


class ResetRequest(BaseModel):
    book_id: str = Field(..., min_length=1)
    page_id: str = Field(..., min_length=1)


def _session_key(book_id: str, page_id: str) -> str:
    """一页一个内核。页在课程里对应一课，也就对应一份 notebook。"""
    return f"{book_id}:{page_id}"


def _load_page(book_id: str, page_id: str):
    from deeptutor.book.storage import BookStorage

    page = BookStorage().load_page(book_id, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="找不到这一页，书可能已被删除或重新导入过。")
    return page


def _runnable_blocks(page) -> list:
    """这一页里按顺序排列的可运行代码格。"""
    out = []
    for block in page.blocks:
        payload = block.payload or {}
        if (payload.get("notebook") or {}).get("runnable"):
            out.append(block)
    return out


def _block_language(block) -> str:
    return str((block.payload or {}).get("language") or "python").strip().lower()


def _prelude_files(page) -> dict[str, str]:
    """读这一页所在目录下 ``_prelude/`` 里的 .go 文件，作为累积编译的底稿。

    没有这个目录就返回空字典——旧讲义（自带完整「本章起点」那种）照跑不误。
    """
    from pathlib import Path as _Path

    cwd = ""
    for block in _runnable_blocks(page):
        cwd = str(((block.payload or {}).get("notebook") or {}).get("cwd") or "")
        if cwd:
            break
    if not cwd:
        return {}

    prelude_dir = _Path(cwd) / "_prelude"
    if not prelude_dir.is_dir():
        return {}

    out: dict[str, str] = {}
    for path in sorted(prelude_dir.glob("*.go")):
        try:
            out[path.name] = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("读不了底稿文件 %s，跳过", path)
    return out


def _go_snippet(page, target_block_id: str, override_code: str, session_key: str) -> str:
    """把这一页到目标格为止的所有 Go 代码凑齐，生成一段编译并运行它的 Python。

    Go 是编译型语言，一段代码要能跑，它依赖的类型和函数必须在同一次编译里都在场，
    所以这里不存在「只跑这一格」——语义只能是「跑到这一格为止」。
    """
    from deeptutor_ext.kernel import build_runner_snippet, filename_for, has_main

    files: dict[str, str] = {}
    runnable = False

    # 先铺这一部分的公共底稿。讲义因此不必每章开头重贴一遍前面章节的成果，
    # 而是在 <本页所在目录>/_prelude/ 放几个 .go 文件。
    #
    # 同名以页面里的格子为准（下面的循环后写覆盖先写），这样学生想改掉某个
    # 铺底文件时，写一个同名的格子就行。
    for name, body in _prelude_files(page).items():
        files[name] = body

    for index, block in enumerate(_runnable_blocks(page), start=1):
        if _block_language(block) not in ("go", "golang"):
            continue
        code = str((block.payload or {}).get("code") or "")
        if block.id == target_block_id and override_code.strip():
            code = override_code
        if not code.strip():
            continue
        files[filename_for(code, index)] = code
        if has_main(code):
            runnable = True
        if block.id == target_block_id:
            break

    if not files:
        raise HTTPException(status_code=400, detail="这一页没有可编译的 Go 代码。")

    from deeptutor.services.path_service import get_path_service

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_key)[:64]
    module_dir = str(
        get_path_service().get_task_workspace("chat", f"notebook_{safe}") / "go_module"
    )
    return build_runner_snippet(files, module_dir=module_dir, runnable=runnable)


def _resolve_cell(page, block_id: str) -> tuple[str, str]:
    """从页里取出这一格的源码与工作目录。"""
    block = page.block_by_id(block_id) if block_id else None
    if block is None:
        raise HTTPException(status_code=404, detail="找不到这一格。")
    payload = block.payload or {}
    notebook = payload.get("notebook") or {}
    return str(payload.get("code") or ""), str(notebook.get("cwd") or "")


def _validated_cwd(raw: str) -> str:
    if not raw:
        return ""
    resolved = Path(raw).expanduser().resolve()
    root = _courses_root()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(
            status_code=400,
            detail=f"这一格的工作目录不在课程目录内，拒绝执行。课程目录是 {root}。",
        )
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail=f"工作目录不存在：{resolved}")
    return str(resolved)


@router.post("/run")
async def run_cell(body: RunCellRequest) -> dict:
    """执行一格，返回结构化输出。图片已经落成文件，返回的是可直接展示的地址。"""
    page = _load_page(body.book_id, body.page_id)
    stored_code, stored_cwd = _resolve_cell(page, body.block_id)
    code = body.code if body.code.strip() else stored_code
    if not code.strip():
        raise HTTPException(status_code=400, detail="这一格没有可执行的代码。")

    cwd = _validated_cwd(body.cwd or stored_cwd)
    session_key = _session_key(body.book_id, body.page_id)
    manager = get_session_manager()

    # Go 走另一条路：它没有长驻状态，只能把到这一格为止的代码凑齐一起编译。
    # 「运行」与「从头跑到这」对 Go 是同一件事，所以这里不分两种情况。
    block = page.block_by_id(body.block_id)
    if block is not None and _block_language(block) in ("go", "golang"):
        snippet = _go_snippet(page, body.block_id, body.code, session_key)
        try:
            result = await manager.execute(
                session_key, snippet, cwd=cwd, timeout_s=body.timeout_s or 180
            )
        except KernelUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        payload = result.to_dict()
        payload["block_id"] = body.block_id
        payload["language"] = "go"
        payload["preceding"] = []
        return payload

    preceding: list[dict] = []
    try:
        if body.through:
            for block in _runnable_blocks(page):
                if block.id == body.block_id:
                    break
                earlier = str((block.payload or {}).get("code") or "")
                if not earlier.strip():
                    continue
                outcome = await manager.execute(
                    session_key, earlier, cwd=cwd, timeout_s=body.timeout_s
                )
                preceding.append(
                    {
                        "block_id": block.id,
                        "status": outcome.status,
                        "cell_index": (block.payload or {}).get("notebook", {}).get("cell_index"),
                    }
                )
                # 前面某一格失败了就停下：接着跑只会连锁报错，把真正的原因埋掉。
                if outcome.status != "ok":
                    failed = result_of_failure(outcome, block.id, preceding)
                    return failed

        result = await manager.execute(
            session_key, code, cwd=cwd, timeout_s=body.timeout_s
        )
    except KernelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    payload = result.to_dict()
    payload["block_id"] = body.block_id
    payload["preceding"] = preceding
    return payload


def result_of_failure(outcome, block_id: str, preceding: list[dict]) -> dict:
    """前置格子失败时的返回：把失败那一格的输出原样带回去，让学生看到真正的原因。"""
    payload = outcome.to_dict()
    payload["block_id"] = block_id
    payload["preceding"] = preceding
    payload["stopped_at_preceding"] = True
    return payload


@router.post("/reset")
async def reset_kernel(body: ResetRequest) -> dict:
    """丢掉这一页的内核，下次运行时是一个干净的环境。"""
    await get_session_manager().reset(_session_key(body.book_id, body.page_id))
    return {"ok": True}


@router.get("/status")
async def kernel_status() -> dict:
    """内核容器是否可用、当前有哪些活着的会话。前端用它决定运行按钮要不要禁用。"""
    from deeptutor_ext.kernel import client

    available = await client.ping()
    return {
        "available": available,
        "base_url": kernel_config.BASE_URL,
        "sessions": get_session_manager().describe(),
        "courses_root": str(_courses_root()),
        "hint": ""
        if available
        else "内核容器没有应答。在服务器上执行：cd ~/DeepTutor-ext && make kernel-start",
    }


# ── 课程模块 ────────────────────────────────────────────────────────────────


class CreateCourseRequest(BaseModel):
    # Git 仓库地址，或本机上的一个目录
    origin: str = Field(..., min_length=1)
    title: str = Field(default="")
    slug: str = Field(default="")
    language: str = Field(default="zh")
    branch: str = Field(default="")
    replace: bool = False
    # 导入后顺带建检索索引。这一步要把全课正文过一遍向量化，慢，所以默认不做。
    build_index: bool = False


class DeleteCourseRequest(BaseModel):
    drop_book: bool = True
    drop_kb: bool = True


@course_router.get("/list")
async def list_courses() -> dict:
    from deeptutor_ext.course import get_course_service

    return {"courses": [record.to_dict() for record in get_course_service().list_courses()]}


@course_router.post("/create")
async def create_course(body: CreateCourseRequest) -> dict:
    """取一门课进来并导成书。可选顺带建检索索引。"""
    import asyncio

    from deeptutor_ext.course import SourceError, get_course_service

    service = get_course_service()
    try:
        # 克隆和解析都是同步的重活，放线程里跑，别把事件循环占住。
        record = await asyncio.to_thread(
            service.create,
            body.origin,
            title=body.title,
            slug=body.slug,
            language=body.language,
            branch=body.branch,
            replace=body.replace,
        )
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("导入课程失败")
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}") from exc

    if body.build_index:
        try:
            await service.build_index(record.slug)
            record = service.get(record.slug) or record
        except Exception as exc:
            logger.exception("建检索索引失败")
            return {
                "course": record.to_dict(),
                "index_error": f"课程已导入，但建检索索引失败：{exc}",
            }
    return {"course": record.to_dict()}


@course_router.post("/{slug}/index")
async def build_course_index(slug: str) -> dict:
    """给这门课建检索索引并绑到它的书上。已经有索引就重建。"""
    from deeptutor_ext.course import SourceError, get_course_service

    service = get_course_service()
    try:
        kb_name = await service.build_index(slug)
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("建检索索引失败")
        raise HTTPException(status_code=500, detail=f"建索引失败：{exc}") from exc
    record = service.get(slug)
    return {"kb_name": kb_name, "course": record.to_dict() if record else None}


@course_router.get("/{slug}/export")
async def export_course_package(slug: str):
    """把这门课打成一个包，供下载后拿到别的机器上导入。"""
    import asyncio

    from deeptutor_ext.course import SourceError, export_course

    try:
        path = await asyncio.to_thread(export_course, slug)
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("打包课程失败")
        raise HTTPException(status_code=500, detail=f"打包失败：{exc}") from exc
    return FileResponse(
        path,
        media_type="application/gzip",
        filename=path.name,
    )


@course_router.post("/import-package")
async def import_course_package(
    file: UploadFile = File(...),
    slug: str = Form(default=""),
    title: str = Form(default=""),
    language: str = Form(default=""),
    replace: bool = Form(default=False),
) -> dict:
    """导入一个课程包。包里只有课程原文，课本在本机重新生成。"""
    import asyncio
    import shutil
    import tempfile
    from pathlib import Path as _Path

    from deeptutor_ext.course import SourceError, import_package

    suffix = _Path(file.filename or "course.dtcourse").suffix or ".dtcourse"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as staging:
        shutil.copyfileobj(file.file, staging)
        staged = _Path(staging.name)

    try:
        record = await asyncio.to_thread(
            import_package,
            staged,
            slug=slug,
            title=title,
            language=language,
            replace=replace,
        )
    except SourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("导入课程包失败")
        raise HTTPException(status_code=500, detail=f"导入失败：{exc}") from exc
    finally:
        staged.unlink(missing_ok=True)

    return {"course": record.to_dict()}


@course_router.post("/{slug}/delete")
async def delete_course(slug: str, body: DeleteCourseRequest) -> dict:
    from deeptutor_ext.course import SourceError, get_course_service

    try:
        outcome = get_course_service().delete(
            slug, drop_book=body.drop_book, drop_kb=body.drop_kb
        )
    except SourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": outcome}


def attach(app) -> None:
    """把这些路由挂到宿主的应用上。由站点钩子在宿主应用加载完成后调用。"""
    if any(getattr(route, "path", "").startswith("/api/v1/ext/notebook") for route in app.routes):
        return
    dependencies = []
    try:
        from fastapi import Depends

        from deeptutor.api.routers.auth import require_auth

        dependencies = [Depends(require_auth)]
    except Exception:
        # 宿主没开鉴权（单机部署的默认情况）时这里拿不到依赖，直接挂无依赖版本。
        logger.debug("取不到宿主的鉴权依赖，扩展路由不做鉴权", exc_info=True)
    app.include_router(
        router,
        prefix="/api/v1/ext/notebook",
        tags=["ext-notebook"],
        dependencies=dependencies,
    )
    app.include_router(
        course_router,
        prefix="/api/v1/ext/course",
        tags=["ext-course"],
        dependencies=dependencies,
    )
    logger.info("扩展接口已挂载：/api/v1/ext/notebook 与 /api/v1/ext/course")


__all__ = ["attach", "router"]

"""课程模块：把外部课程取进来，变成可读、可练、可检索的一门课。"""

from deeptutor_ext.course.importer import CourseImporter
from deeptutor_ext.course.notebook_io import parse_notebook, to_teaching_markdown
from deeptutor_ext.course.service import CourseRecord, CourseService, get_course_service
from deeptutor_ext.course.sources import SourceError

__all__ = [
    "CourseImporter",
    "CourseRecord",
    "CourseService",
    "SourceError",
    "get_course_service",
    "parse_notebook",
    "to_teaching_markdown",
]

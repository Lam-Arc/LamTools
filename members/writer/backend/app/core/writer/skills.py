from app.core.resource_dirs import core_resource_roots, writer_resource_roots
from lamtools_core.skills import Skill as WriterSkill
from lamtools_core.skills import SkillRegistry


class WriterSkillRegistry(SkillRegistry):
    """Discovers Writer skills and loads full skill content on demand."""

    def __init__(self, max_content_chars: int = 30000, sample_files: int = 10):
        super().__init__(
            explicit_roots=[*writer_resource_roots(), *core_resource_roots()],
            max_content_chars=max_content_chars,
            sample_files=sample_files,
        )

    def prompt_index(self, work_root) -> str:
        skills = self.available(work_root)
        if not skills:
            return ""
        lines = [
            "Available Writer skills:",
            "Use load_skill only when the current task matches a skill description.",
            "<available_skills>",
        ]
        for skill in skills:
            lines.extend(
                [
                    "  <skill>",
                    f"    <name>{skill.name}</name>",
                    f"    <description>{skill.description}</description>",
                    f"    <location>{skill.location}</location>",
                    "  </skill>",
                ]
            )
        lines.append("</available_skills>")
        return "\n".join(lines)

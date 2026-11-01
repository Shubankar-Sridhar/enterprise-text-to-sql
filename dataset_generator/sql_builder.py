# sql_builder.py
from .templates import SlotBinding, Template

def build_sql(template: Template, binding: SlotBinding) -> str:
    return template.build_sql(binding)
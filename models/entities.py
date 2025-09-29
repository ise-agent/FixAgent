"""Entity models for code knowledge graph"""
from typing import List, Optional
from pydantic import BaseModel


class Clazz(BaseModel):
    """Class entity model"""
    name: str
    full_qualified_name: str
    absolute_path: str
    start_line: int
    end_line: int
    content: str
    class_type: str
    parent_classes: List[str]

    class Config:
        # Allow assignment to fields after model creation
        validate_assignment = True


class Method(BaseModel):
    """Method entity model"""
    name: str
    full_qualified_name: str
    absolute_path: str
    start_line: int
    end_line: int
    content: str
    params: List[str]
    modifiers: List[str]
    signature: str
    type: Optional[str] = None

    class Config:
        validate_assignment = True


class Variable(BaseModel):
    """Variable entity model"""
    name: str
    full_qualified_name: str
    absolute_path: str
    start_line: int
    end_line: int
    content: str
    modifiers: List[str]
    data_type: str

    class Config:
        validate_assignment = True
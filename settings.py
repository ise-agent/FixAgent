from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration settings with support for environment variables."""

    # LLM API Settings
    openai_api_key: str = Field(default="sk-NdZukOuQQRhydvPW33Dc1e05AbCa4fE394BfD3FfB9Ac09Be", env="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.holdai.top/v1", env="OPENAI_BASE_URL")
    openai_model: str = Field(default="claude-sonnet-4-20250514", env="OPENAI_MODEL")

    claude_api_key: str = Field(default="", env="CLAUDE_API_KEY")
    claude_base_url: str = Field(default="", env="CLAUDE_BASE_URL")
    claude_model: str = Field(default="", env="CLAUDE_MODEL")

    relay_api_key: Optional[str] = Field(default=None, env="RELAY_API_KEY")
    relay_base_url: Optional[str] = Field(default=None, env="RELAY_BASE_URL")

    # Neo4j Database Settings
    neo4j_uri: str = Field(default="bolt://localhost:7687", env="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", env="NEO4J_USER")
    neo4j_password: str = Field(default="12345678", env="NEO4J_PASSWORD")

    # Project Settings
    test_bed: str = Field(default="/tmp/test", env="TEST_BED")
    project_name: str = Field(default="test_project", env="PROJECT_NAME")
    instance_id: str = Field(default="test_instance", env="INSTANCE_ID")
    problem_statement: str = Field(default="Find and fix bugs in the project", env="PROBLEM_STATEMENT")


    round: str = Field(default="AAA_jiancaihange", env="ROUND")
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
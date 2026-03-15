"""
配置文件管理
"""
from pydantic import BaseSettings, Field
from typing import Dict, Optional
import os


class QoderInstanceConfig(BaseSettings):
    """单个 Qoder 实例配置"""
    name: str = Field(..., description="Qoder 实例名称")
    workdir: str = Field(..., description="Qoder 工作目录")
    cmd: str = Field(default="qoder", description="启动命令")
    auto_start: bool = Field(default=False, description="是否自动启动")
    max_restarts: int = Field(default=3, description="最大重启次数")


class FeishuBotConfig(BaseSettings):
    """飞书机器人配置"""
    app_id: str = Field(..., description="飞书应用 App ID")
    app_secret: str = Field(..., description="飞书应用 App Secret")
    verification_token: str = Field(..., description="验证 Token")
    encrypt_key: Optional[str] = Field(None, description="加密密钥（可选）")
    qoder_instance: str = Field(..., description="关联的 Qoder 实例名称")
    enabled: bool = Field(default=True, description="是否启用")


class SystemConfig(BaseSettings):
    """系统级配置"""
    # 服务配置
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8080, description="监听端口")
    
    # Redis 配置
    redis_host: str = Field(default="localhost", description="Redis 主机")
    redis_port: int = Field(default=6379, description="Redis 端口")
    redis_db: int = Field(default=0, description="Redis 数据库")
    redis_password: Optional[str] = Field(None, description="Redis 密码")
    
    # 日志配置
    log_level: str = Field(default="INFO", description="日志级别")
    log_file: str = Field(default="logs/qoderclaw.log", description="日志文件")
    
    # 健康检查
    health_check_interval: int = Field(default=30, description="健康检查间隔（秒）")
    heartbeat_timeout: int = Field(default=120, description="心跳超时时间（秒）")
    
    # 会话配置
    session_timeout: int = Field(default=3600, description="会话超时时间（秒）")
    max_message_length: int = Field(default=4000, description="单条消息最大长度")


class Config(BaseSettings):
    """主配置类"""
    system: SystemConfig = Field(default_factory=SystemConfig)
    feishu_bots: Dict[str, FeishuBotConfig] = Field(default_factory=dict)
    qoder_instances: Dict[str, QoderInstanceConfig] = Field(default_factory=dict)
    
    class Config:
        env_file = ".env"
        env_nested_delimiter = "__"
    
    @classmethod
    def load_from_file(cls, config_path: str = "config.yaml") -> "Config":
        """从 YAML 文件加载配置"""
        import yaml
        
        if not os.path.exists(config_path):
            print(f"配置文件 {config_path} 不存在，使用默认配置")
            return cls()
        
        with open(config_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        return cls(**data)


# 全局配置实例
config = Config.load_from_file()

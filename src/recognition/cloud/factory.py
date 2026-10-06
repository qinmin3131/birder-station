"""
识别器工厂模块

根据配置和请求创建对应的识别器实例。
"""
import threading
from typing import Dict, Type, Optional, Any
from ..base import AbstractBirdRecognizer
from ..protocol import RecognitionPlatform
from .huggingface import HuggingFaceRecognizer
from .modelscope import ModelScopeRecognizer
from .aliyun import AliyunRecognizer
from .baidu import BaiduRecognizer
from ..inference_dongniao import DongniaoRecognizer
from ...utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


class RecognizerFactory:
    """识别器工厂"""

    # 平台到识别器类的映射
    _recognizers: Dict[str, Type[AbstractBirdRecognizer]] = {
        RecognitionPlatform.huggingface.value: HuggingFaceRecognizer,
        RecognitionPlatform.modelscope.value: ModelScopeRecognizer,
        RecognitionPlatform.aliyun.value: AliyunRecognizer,
        RecognitionPlatform.baidu.value: BaiduRecognizer,
        "dongniao": DongniaoRecognizer,  # 懂鸟 API
    }

    # 本地识别器（BioCLIP）加载昂贵且持有实例级 text features 缓存，
    # 在进程内复用单例，避免每次请求都重新加载模型 + 重新编码上千个候选标签。
    # 仅当调用方未传额外 kwargs（即 Web API 的默认调用路径）时启用单例；
    # 显式传 kwargs 的调用（如测试、自定义 model_name/device）走新建路径。
    _local_recognizer: Optional[Any] = None
    _local_recognizer_lock = threading.Lock()

    @classmethod
    def create(
        cls,
        platform: str,
        **kwargs
    ) -> AbstractBirdRecognizer:
        """
        创建识别器实例

        Args:
            platform: 平台标识符
            **kwargs: 额外的初始化参数。本地识别器在无 kwargs 时返回进程级单例，
                有 kwargs 时每次新建以尊重调用方指定的参数。

        Returns:
            识别器实例

        Raises:
            ValueError: 未知平台
            RuntimeError: 识别器不可用
        """
        if platform not in cls._recognizers:
            # 如果是本地识别，尝试加载本地识别器
            if platform == RecognitionPlatform.local.value:
                return cls._get_local_recognizer(kwargs)
            raise ValueError(f"Unknown platform: {platform}")

        recognizer_class = cls._recognizers[platform]

        # 尝试创建实例
        try:
            recognizer = recognizer_class(**kwargs)

            # 检查是否可用
            if hasattr(recognizer, 'is_available') and not recognizer.is_available:
                raise RuntimeError(f"{platform} recognizer is not available. Please check API keys.")

            return recognizer

        except ValueError as e:
            logger.error(f"Failed to create {platform} recognizer: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating {platform} recognizer: {e}")
            raise RuntimeError(f"Failed to initialize {platform} recognizer: {e}")

    @classmethod
    def _get_local_recognizer(cls, kwargs: Dict[str, Any]) -> "AbstractBirdRecognizer":
        """获取本地识别器：无 kwargs 时复用进程级单例，有 kwargs 时新建。"""
        from ..inference_local import LocalBirdRecognizer
        config = get_config()
        rec_config = config.get('recognition', {})
        hf_mirror = rec_config.get('hf_mirror')
        create_kwargs = {**kwargs, 'hf_mirror': hf_mirror}

        # 显式传参（如 model_name/device）→ 不走单例，尊重调用方参数
        if kwargs:
            return LocalBirdRecognizer(**create_kwargs)

        # 快路径：单例已就绪直接返回
        if cls._local_recognizer is not None:
            return cls._local_recognizer

        with cls._local_recognizer_lock:
            if cls._local_recognizer is not None:
                return cls._local_recognizer
            # 构造失败不缓存，让后续请求可重试
            recognizer = LocalBirdRecognizer(**create_kwargs)
            cls._local_recognizer = recognizer
            logger.info("LocalBirdRecognizer singleton cached for process-wide reuse.")
            return recognizer

    @classmethod
    def create_from_request(cls, request) -> AbstractBirdRecognizer:
        """从请求对象创建识别器"""
        platform = request.platform.value if hasattr(request.platform, 'value') else request.platform
        return cls.create(platform)

    @classmethod
    def register(cls, platform: str, recognizer_class: Type[AbstractBirdRecognizer]):
        """注册新的识别器"""
        cls._recognizers[platform] = recognizer_class
        logger.info(f"Registered recognizer for platform: {platform}")

    @classmethod
    def get_available_platforms(cls) -> list:
        """获取可用的平台列表"""
        available = []
        for platform, recognizer_class in cls._recognizers.items():
            try:
                recognizer = recognizer_class()
                if recognizer.is_available:
                    available.append(platform)
            except Exception:
                continue
        return available

    @classmethod
    def get_all_platforms(cls) -> list:
        """获取所有已注册的平台"""
        return list(cls._recognizers.keys())


def get_default_config() -> Dict[str, Any]:
    """获取各平台的默认配置"""
    config = get_config()
    cloud_config = config.get("cloud", {})

    return {
        "huggingface": {
            "api_token": cloud_config.get("huggingface", {}).get("api_token"),
            "model_id": cloud_config.get("huggingface", {}).get("model_id"),
        },
        "modelscope": {
            "api_token": cloud_config.get("modelscope", {}).get("api_token"),
            "model_id": cloud_config.get("modelscope", {}).get("model_id"),
        },
        "aliyun": {
            "access_key_id": cloud_config.get("aliyun", {}).get("access_key_id"),
            "access_key_secret": cloud_config.get("aliyun", {}).get("access_key_secret"),
        },
        "baidu": {
            "api_key": cloud_config.get("baidu", {}).get("api_key"),
            "secret_key": cloud_config.get("baidu", {}).get("secret_key"),
        },
    }

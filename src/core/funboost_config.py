# funboost_config.py
import os
from funboost.constant import BrokerEnum

# Redis配置（根据你的环境调整）
REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', '')
REDIS_DB = int(os.getenv('REDIS_DB', 0))

# 设置默认的broker类型为Redis
DEFAULT_BROKER_KIND = BrokerEnum.REDIS_ACK_ABLE

# 其他funboost配置可以在这里添加

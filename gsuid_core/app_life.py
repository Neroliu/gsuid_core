import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from gsuid_core.aps import start_scheduler, shutdown_scheduler
from gsuid_core.logger import logger, clean_log
from gsuid_core.server import core_start_execute, core_shutdown_execute, core_start_before_execute
from gsuid_core.shutdown import shutdown_event


@asynccontextmanager
async def lifespan(app: FastAPI):
    from gsuid_core.global_val import trans_global_val
    from gsuid_core.webconsole import _setup_frontend
    from gsuid_core.utils.download_resource.download_core import check_speed

    # 先执行启动前钩子（数据库迁移、全局变量加载等），阻塞式
    await core_start_before_execute()

    # 提前触发测速预热，完全独立运行，不阻塞任何启动流程
    asyncio.create_task(check_speed())

    # 将 core_start_execute 移到后台执行，不阻塞 WS 服务启动
    # 这样 WS 可以先建立连接，启动钩子在后台异步完成
    asyncio.create_task(core_start_execute())
    await _setup_frontend()
    await start_scheduler()
    await trans_global_val()

    asyncio.create_task(clean_log())

    yield

    logger.info("[GsCore] 开始关闭流程，设置 shutdown_event...")
    shutdown_event.set()

    await shutdown_scheduler()
    await core_shutdown_execute()


app = FastAPI(lifespan=lifespan)

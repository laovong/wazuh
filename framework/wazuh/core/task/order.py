import asyncio
from dataclasses import asdict

import httpx

from wazuh.core import common
from wazuh.core.wlogging import WazuhLogger
from wazuh.core.engine.base import APPLICATION_JSON
from wazuh.core.indexer import get_indexer_client
from wazuh.core.indexer.models.commands import Status
from wazuh.core.indexer.utils import convert_enums

COMMANDS_KEY = 'commands'
WAIT_UNTIL_NEXT_PULL = 10


async def get_orders(logger: WazuhLogger):
    """Get orders from the indexer and send them to the Communications API unix socket HTTP server."""

    transport = httpx.AsyncHTTPTransport(uds=common.COMMS_API_SOCKET_PATH)
    client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(10))

    while True:
        await asyncio.sleep(WAIT_UNTIL_NEXT_PULL)
        logger.info('Getting orders from indexer')

        async with get_indexer_client() as indexer_client:
            pending_commands = await indexer_client.commands_manager.get_commands(Status.PENDING.value)
            logger.debug(f'Commands index response: {pending_commands}')
            pending_commands = {
                COMMANDS_KEY: [asdict(command, dict_factory=convert_enums) for command in pending_commands]
            }

            if not pending_commands[COMMANDS_KEY]:
                continue

            try:
                response = await client.post(
                    url='http://localhost/api/v1/commands',
                    json=pending_commands,
                    headers={
                        'Accept': APPLICATION_JSON,
                        'Content-Type': APPLICATION_JSON,
                    }
                )

                logger.debug(f'Post orders response: {response.status_code} - {response.json()}')

                if response.status_code != 200:
                    logger.error(f'Post orders failed: {response.status_code} - {response.json()}')
                    continue

                processed_commands = response.json()[COMMANDS_KEY]

                if processed_commands:
                    processed_commands_ids = [item['order_id'] for item in processed_commands]
                    logger.info(f'Updating processed commands: {processed_commands_ids}')

                    await indexer_client.commands_manager.update_commands_status(
                        order_ids=processed_commands_ids,
                        status=Status.SENT.value
                    )


            except (httpx.ConnectError, httpx.TimeoutException) as e:
                logger.error(f'An error occurs sending the orders to the Communications API :', str(e))

from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT NOT NULL;"""

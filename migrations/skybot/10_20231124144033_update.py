from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponder` MODIFY COLUMN `response` VARCHAR(2000);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponder` MODIFY COLUMN `response` VARCHAR(2000) NOT NULL;"""

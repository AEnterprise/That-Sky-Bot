from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `attachments` MODIFY COLUMN `url` VARCHAR(1024) NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `attachments` MODIFY COLUMN `url` VARCHAR(255) NOT NULL;"""

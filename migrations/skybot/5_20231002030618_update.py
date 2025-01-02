from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponse` RENAME COLUMN `message_type` TO `type`;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponse` RENAME COLUMN `type` TO `message_type`;"""

from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponder` ALTER COLUMN `response` SET DEFAULT '';
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `type` SMALLINT NOT NULL  COMMENT 'ignore: 0\nresponse: 1\nlisten: 2\nlog: 3\nmod: 4';
        UPDATE `autoresponderchannel` SET type=0 where type=4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `autoresponder` ALTER COLUMN `response` DROP DEFAULT;
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `type` SMALLINT NOT NULL  COMMENT 'response: 1\nlisten: 2\nlog: 3\nignore: 4';
        UPDATE `autoresponderchannel` SET type=4 where type=0;"""

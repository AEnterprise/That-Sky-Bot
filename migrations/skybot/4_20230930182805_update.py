from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `autoresponderchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `type` SMALLINT NOT NULL  COMMENT 'response: 1\nlisten: 2\nlog: 3\nignore: 4',
    `autoresponder_id` INT NOT NULL,
    UNIQUE KEY `uid_autorespond_autores_753a75` (`autoresponder_id`, `channelid`, `type`),
    CONSTRAINT `fk_autoresp_autoresp_d2fabc65` FOREIGN KEY (`autoresponder_id`) REFERENCES `autoresponder` (`id`) ON DELETE CASCADE,
    KEY `idx_autorespond_autores_bc9d3d` (`autoresponder_id`)
) CHARACTER SET utf8mb4;
        CREATE TABLE IF NOT EXISTS `autoresponse` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `response` VARCHAR(2000) NOT NULL,
    `message_type` SMALLINT NOT NULL  COMMENT 'reply: 1\nmod: 2\nlog: 3',
    `autoresponder_id` INT NOT NULL,
    CONSTRAINT `fk_autoresp_autoresp_5ccd4161` FOREIGN KEY (`autoresponder_id`) REFERENCES `autoresponder` (`id`) ON DELETE CASCADE,
    KEY `idx_autorespons_autores_f32648` (`autoresponder_id`)
) CHARACTER SET utf8mb4;
        ALTER TABLE `guild` ALTER COLUMN `defaultlocale` SET DEFAULT 'en_US';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `guild` ALTER COLUMN `defaultlocale` DROP DEFAULT;
        DROP TABLE IF EXISTS `autoresponderchannel`;
        DROP TABLE IF EXISTS `autoresponse`;"""

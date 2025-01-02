from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `mischiefname` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `name` VARCHAR(36) NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_mischiefnam_name_a3dbcd` (`name`, `guild_id`),
    CONSTRAINT `fk_mischief_guild_ecb1522f` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_mischiefnam_guild_i_afebf5` (`guild_id`)
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS `mischiefname`;"""

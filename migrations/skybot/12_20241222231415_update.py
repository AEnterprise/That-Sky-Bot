from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `adminrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `attachments` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT;
        ALTER TABLE `autoresponse` MODIFY COLUMN `autoresponder_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `platform_id` INT NOT NULL;
        ALTER TABLE `customcommand` ADD `elevated` SMALLINT NOT NULL  DEFAULT 0;
        ALTER TABLE `customcommand` ADD `autocomplete` BOOL NOT NULL  DEFAULT 0;
        ALTER TABLE `krillbylines` MODIFY COLUMN `krill_config_id` INT NOT NULL;
        ALTER TABLE `krillconfig` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `localization` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `modrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `repros` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `trustedrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `userpermission` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `watchedemoji` MODIFY COLUMN `watcher_id` INT NOT NULL;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE `repros` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `modrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `adminrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `attachments` MODIFY COLUMN `report_id` INT NOT NULL;
        ALTER TABLE `krillconfig` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `trustedrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `autoresponse` MODIFY COLUMN `autoresponder_id` INT NOT NULL;
        ALTER TABLE `krillbylines` MODIFY COLUMN `krill_config_id` INT NOT NULL;
        ALTER TABLE `localization` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `mischiefrole` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `watchedemoji` MODIFY COLUMN `watcher_id` INT NOT NULL;
        ALTER TABLE `customcommand` DROP COLUMN `elevated`;
        ALTER TABLE `customcommand` DROP COLUMN `autocomplete`;
        ALTER TABLE `userpermission` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `guild_id` INT NOT NULL;
        ALTER TABLE `bugreportingchannel` MODIFY COLUMN `platform_id` INT NOT NULL;
        ALTER TABLE `autoresponderchannel` MODIFY COLUMN `autoresponder_id` INT;"""

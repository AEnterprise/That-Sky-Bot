from tortoise import BaseDBAsyncClient


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS `artchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `listenchannelid` BIGINT NOT NULL  DEFAULT 0,
    `collectionchannelid` BIGINT NOT NULL  DEFAULT 0,
    `tag` VARCHAR(30) NOT NULL  DEFAULT '',
    UNIQUE KEY `uid_artchannel_serveri_dacf81` (`serverid`, `listenchannelid`, `collectionchannelid`, `tag`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `autoresponder` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(300) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `flags` SMALLINT NOT NULL  DEFAULT 0,
    `chance` SMALLINT NOT NULL  DEFAULT 10000,
    `responsechannelid` BIGINT NOT NULL  DEFAULT 0,
    `listenchannelid` BIGINT NOT NULL  DEFAULT 0,
    `logchannelid` BIGINT NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_autorespond_trigger_d7d834` (`trigger`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `botadmin` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `userid` BIGINT NOT NULL UNIQUE
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreport` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `reporter` BIGINT NOT NULL,
    `message_id` BIGINT  UNIQUE,
    `attachment_message_id` BIGINT  UNIQUE,
    `platform` VARCHAR(10) NOT NULL,
    `platform_version` VARCHAR(20) NOT NULL,
    `branch` VARCHAR(10) NOT NULL,
    `app_version` VARCHAR(20) NOT NULL,
    `app_build` VARCHAR(20),
    `title` VARCHAR(330) NOT NULL,
    `deviceinfo` VARCHAR(100) NOT NULL,
    `steps` VARCHAR(1024) NOT NULL,
    `expected` VARCHAR(880) NOT NULL,
    `actual` VARCHAR(880) NOT NULL,
    `additional` VARCHAR(500) NOT NULL,
    `reported_at` BIGINT NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `attachments` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `url` VARCHAR(255) NOT NULL,
    `report_id` INT NOT NULL,
    UNIQUE KEY `uid_attachments_report__89548d` (`report_id`, `url`),
    CONSTRAINT `fk_attachme_bugrepor_0d8fd583` FOREIGN KEY (`report_id`) REFERENCES `bugreport` (`id`) ON DELETE CASCADE,
    KEY `idx_attachments_report__4bd92e` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingplatform` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `platform` VARCHAR(100) NOT NULL,
    `branch` VARCHAR(20) NOT NULL,
    UNIQUE KEY `uid_bugreportin_platfor_fb781e` (`platform`, `branch`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `configchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `configname` VARCHAR(100) NOT NULL,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_configchann_confign_21c1ab` (`configname`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `countword` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `word` VARCHAR(300) NOT NULL,
    UNIQUE KEY `uid_countword_word_931444` (`word`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `customcommand` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `trigger` VARCHAR(20) NOT NULL,
    `response` VARCHAR(2000) NOT NULL,
    `deletetrigger` BOOL NOT NULL  DEFAULT 0,
    `reply` BOOL NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_customcomma_trigger_65c25c` (`trigger`, `serverid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `dropboxchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `sourcechannelid` BIGINT NOT NULL,
    `targetchannelid` BIGINT NOT NULL  DEFAULT 0,
    `deletedelayms` SMALLINT NOT NULL  DEFAULT 0,
    `sendreceipt` BOOL NOT NULL  DEFAULT 0,
    UNIQUE KEY `uid_dropboxchan_serveri_7254d9` (`serverid`, `sourcechannelid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `guild` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL UNIQUE,
    `memberrole` BIGINT NOT NULL  DEFAULT 0,
    `nonmemberrole` BIGINT NOT NULL  DEFAULT 0,
    `mutedrole` BIGINT NOT NULL  DEFAULT 0,
    `betarole` BIGINT NOT NULL  DEFAULT 0,
    `welcomechannelid` BIGINT NOT NULL  DEFAULT 0,
    `ruleschannelid` BIGINT NOT NULL  DEFAULT 0,
    `logchannelid` BIGINT NOT NULL  DEFAULT 0,
    `entrychannelid` BIGINT NOT NULL  DEFAULT 0,
    `maintenancechannelid` BIGINT NOT NULL  DEFAULT 0,
    `rulesreactmessageid` BIGINT NOT NULL  DEFAULT 0,
    `defaultlocale` VARCHAR(10) NOT NULL
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `adminrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_adminrole_roleid_457f6b` (`roleid`, `guild_id`),
    CONSTRAINT `fk_adminrol_guild_56368cba` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_adminrole_guild_i_1576b8` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `bugreportingchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    `platform_id` INT NOT NULL,
    UNIQUE KEY `uid_bugreportin_guild_i_91e902` (`guild_id`, `platform_id`),
    CONSTRAINT `fk_bugrepor_guild_04eb4078` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_bugrepor_bugrepor_2f3979ee` FOREIGN KEY (`platform_id`) REFERENCES `bugreportingplatform` (`id`) ON DELETE CASCADE,
    KEY `idx_bugreportin_guild_i_e13b1e` (`guild_id`),
    KEY `idx_bugreportin_platfor_fe0d79` (`platform_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillchannel` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL,
    `channelid` BIGINT NOT NULL,
    UNIQUE KEY `uid_krillchanne_serveri_5da66e` (`serverid`, `channelid`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillconfig` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `return_home_freq` SMALLINT NOT NULL  DEFAULT 0,
    `shadow_roll_freq` SMALLINT NOT NULL  DEFAULT 0,
    `krill_rider_freq` SMALLINT NOT NULL  DEFAULT 0,
    `crab_freq` SMALLINT NOT NULL  DEFAULT 0,
    `allow_text` BOOL NOT NULL  DEFAULT 1,
    `monster_duration` SMALLINT NOT NULL  DEFAULT 21600,
    `guild_id` INT NOT NULL UNIQUE,
    CONSTRAINT `fk_krillcon_guild_43a114df` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_krillconfig_guild_i_bc8ec8` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `krillbylines` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `byline` VARCHAR(100) NOT NULL,
    `type` SMALLINT NOT NULL  DEFAULT 0,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    `locale` VARCHAR(10) NOT NULL  DEFAULT '',
    `krill_config_id` INT NOT NULL,
    UNIQUE KEY `uid_krillbyline_krill_c_b18cc4` (`krill_config_id`, `byline`, `type`),
    CONSTRAINT `fk_krillbyl_krillcon_04799d75` FOREIGN KEY (`krill_config_id`) REFERENCES `krillconfig` (`id`) ON DELETE CASCADE,
    KEY `idx_krillbyline_krill_c_95a61d` (`krill_config_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `localization` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `channelid` BIGINT NOT NULL  DEFAULT 0,
    `locale` VARCHAR(10) NOT NULL  DEFAULT '',
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_localizatio_guild_i_1e041d` (`guild_id`, `channelid`),
    CONSTRAINT `fk_localiza_guild_9f755aae` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_localizatio_guild_i_2a3780` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `modrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_modrole_roleid_b1b1c0` (`roleid`, `guild_id`),
    CONSTRAINT `fk_modrole_guild_62488d68` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_modrole_guild_i_cc7b59` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreoletters` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `token` VARCHAR(50) NOT NULL  DEFAULT '',
    `token_class` SMALLINT NOT NULL,
    UNIQUE KEY `uid_oreoletters_token_84fe18` (`token`, `token_class`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `oreomap` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `letter_o` SMALLINT NOT NULL  DEFAULT 1,
    `letter_r` SMALLINT NOT NULL  DEFAULT 2,
    `letter_e` SMALLINT NOT NULL  DEFAULT 3,
    `letter_oh` SMALLINT NOT NULL  DEFAULT 4,
    `letter_re` SMALLINT NOT NULL  DEFAULT 5,
    `space_char` SMALLINT NOT NULL  DEFAULT 6,
    `char_count` VARCHAR(50) NOT NULL  DEFAULT '{0,10}'
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `reactwatch` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `serverid` BIGINT NOT NULL UNIQUE,
    `muteduration` SMALLINT NOT NULL  DEFAULT 600,
    `watchremoves` BOOL NOT NULL  DEFAULT 0
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `repros` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `user` BIGINT NOT NULL,
    `report_id` INT NOT NULL,
    UNIQUE KEY `uid_repros_user_34d996` (`user`, `report_id`),
    CONSTRAINT `fk_repros_bugrepor_b26170f5` FOREIGN KEY (`report_id`) REFERENCES `bugreport` (`id`) ON DELETE CASCADE,
    KEY `idx_repros_report__c7a8a7` (`report_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `trustedrole` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `roleid` BIGINT NOT NULL,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_trustedrole_roleid_215f34` (`roleid`, `guild_id`),
    CONSTRAINT `fk_trustedr_guild_7af9759e` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_trustedrole_guild_i_deb2b1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `userpermission` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `userid` BIGINT NOT NULL,
    `command` VARCHAR(200) NOT NULL  DEFAULT '',
    `allow` BOOL NOT NULL  DEFAULT 1,
    `guild_id` INT NOT NULL,
    UNIQUE KEY `uid_userpermiss_userid_7b40ae` (`userid`, `command`),
    CONSTRAINT `fk_userperm_guild_24ce9edd` FOREIGN KEY (`guild_id`) REFERENCES `guild` (`id`) ON DELETE CASCADE,
    KEY `idx_userpermiss_guild_i_3a0dc1` (`guild_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `watchedemoji` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `emoji` VARCHAR(50) NOT NULL,
    `log` BOOL NOT NULL  DEFAULT 0,
    `remove` BOOL NOT NULL  DEFAULT 0,
    `mute` BOOL NOT NULL  DEFAULT 0,
    `watcher_id` INT NOT NULL,
    UNIQUE KEY `uid_watchedemoj_emoji_4203dc` (`emoji`, `watcher_id`),
    CONSTRAINT `fk_watchede_reactwat_b8aaa411` FOREIGN KEY (`watcher_id`) REFERENCES `reactwatch` (`id`) ON DELETE CASCADE,
    KEY `idx_watchedemoj_watcher_a04b30` (`watcher_id`)
) CHARACTER SET utf8mb4;
CREATE TABLE IF NOT EXISTS `aerich` (
    `id` INT NOT NULL PRIMARY KEY AUTO_INCREMENT,
    `version` VARCHAR(255) NOT NULL,
    `app` VARCHAR(100) NOT NULL,
    `content` JSON NOT NULL
) CHARACTER SET utf8mb4;"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        """

from dataclasses import dataclass
from enum import IntEnum

from tortoise import Tortoise
from tortoise.models import Model
from tortoise.fields import \
    BooleanField, BigIntField, IntField, SmallIntField, CharField, ForeignKeyField, OneToOneField, ReverseRelation, \
    IntEnumField

from utils import tortoise_settings, Logging
from utils.tortoise_settings import app_name as app
import os


async def init(db_name=''):
    #  specify the app name of 'models'
    #  which contain models from "app.models"

    # env var BOT_DB will override db name from both init call AND config.json
    override_db_name = os.getenv('BOT_DB')
    if override_db_name:
        db_name = override_db_name

    settings = tortoise_settings.TORTOISE_ORM
    if db_name:
        settings['connections']['default']['credentials']['database'] = db_name

    Logging.info(f"Database init - \"{settings['connections']['default']['credentials']['database']}\"")
    await Tortoise.init(settings)


class AbstractBaseModel(Model):
    id = IntField(pk=True)

    class Meta:
        abstract = True


class DeprecatedServerIdMixIn:
    serverid = BigIntField()


class GuildMixin:
    guild = OneToOneField(f'{app}.Guild', related_name='krill_config', index=True)


class AdminRole(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='admin_roles', index=True)
    roleid = BigIntField()

    def __str__(self):
        return str(self.roleid)

    class Meta:
        unique_together = ('roleid', 'guild')
        table = 'adminrole'


class ArtChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    # guild = ForeignKeyField(f'{app}.Guild', related_name='artchannels')
    listenchannelid = BigIntField(default=0)
    collectionchannelid = BigIntField(default=0)
    tag = CharField(max_length=30, default="")

    def __str__(self):
        return str(self.listenchannelid)

    class Meta:
        unique_together = ('serverid', 'listenchannelid', 'collectionchannelid', 'tag')
        table = 'artchannel'


class Attachments(AbstractBaseModel):
    url = CharField(max_length=1024)
    report = ForeignKeyField(f'{app}.BugReport', related_name='attachments', index=True)

    def __str__(self):
        return self.url

    class Meta:
        table = 'attachments'


class AutoResponder(AbstractBaseModel, DeprecatedServerIdMixIn):
    trigger = CharField(max_length=300)
    response = CharField(max_length=2000, null=True, default='')
    flags = SmallIntField(default=0)
    chance = SmallIntField(default=10000)
    responsechannelid = BigIntField(default=0)
    listenchannelid = BigIntField(default=0)
    logchannelid = BigIntField(default=0)

    channels: ReverseRelation["AutoResponderChannel"]
    responses: ReverseRelation["AutoResponse"]

    def __str__(self):
        return self.trigger

    class Meta:
        unique_together = ('trigger', 'serverid')
        table = 'autoresponder'


class AutoResponderChannelType(IntEnum):
    ignore = 0
    response = 1
    listen = 2
    log = 3
    mod = 4


class AutoResponseType(IntEnum):
    public = 1
    mod = 2
    log = 3


class AutoResponderChannel(AbstractBaseModel):
    autoresponder = ForeignKeyField(f'{app}.AutoResponder',
                                    related_name='channels',
                                    index=True,
                                    null=True,
                                    default=None)
    channelid = BigIntField()
    type = IntEnumField(AutoResponderChannelType)

    class Meta:
        table = 'autoresponderchannel'


class AutoResponse(AbstractBaseModel):
    autoresponder = ForeignKeyField(f'{app}.AutoResponder', related_name='responses', index=True)
    response = CharField(max_length=2000)
    active = BooleanField(default=True)
    type = IntEnumField(AutoResponseType)

    def __str__(self):
        return str(self.response)

    class Meta:
        table = 'autoresponse'


class BotAdmin(AbstractBaseModel):
    userid = BigIntField(unique=True)

    def __str__(self):
        return str(self.userid)

    class Meta:
        table = 'botadmin'


@dataclass(frozen=True)
class BugReportFieldLength:
    platform: int = 100
    generic_version: int = 20
    platform_version: int = 20
    branch: int = 20
    app_version: int = 20
    app_build: int = 20
    title: int = 330
    deviceinfo: int = 100
    steps: int = 1024
    expected: int = 880
    actual: int = 880
    additional: int = 500


class BugReport(AbstractBaseModel):
    reporter = BigIntField()
    message_id = BigIntField(unique=True, null=True)
    attachment_message_id = BigIntField(unique=True, null=True)
    platform = CharField(BugReportFieldLength.platform)
    platform_version = CharField(BugReportFieldLength.generic_version)
    branch = CharField(BugReportFieldLength.branch)
    app_version = CharField(BugReportFieldLength.generic_version)
    app_build = CharField(BugReportFieldLength.app_build, null=True)
    title = CharField(BugReportFieldLength.title)
    deviceinfo = CharField(BugReportFieldLength.deviceinfo)
    steps = CharField(BugReportFieldLength.steps)
    expected = CharField(BugReportFieldLength.expected)
    actual = CharField(BugReportFieldLength.actual)
    additional = CharField(BugReportFieldLength.additional)
    reported_at = BigIntField()

    attachments: ReverseRelation["Attachments"]
    repros: ReverseRelation["Repros"]

    def __str__(self):
        return f"[{self.id}] {self.reporter}: {self.title} - {self.platform}/{self.branch}"

    class Meta:
        table = 'bugreport'


class BugReportingChannel(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='bug_channels', index=True)
    channelid = BigIntField()
    platform = ForeignKeyField(f'{app}.BugReportingPlatform', related_name="bug_channels", index=True)

    def __str__(self):
        return str(self.channelid)

    class Meta:
        # unique constraint for guild/platform
        unique_together = ('guild', 'platform')
        table = 'bugreportingchannel'


class BugReportingPlatform(AbstractBaseModel):
    platform = CharField(100)
    branch = CharField(20)

    bug_channels: ReverseRelation["BugReportingChannel"]

    def __str__(self):
        return f"{self.platform}_{self.branch}"

    class Meta:
        # unique constraint for platform/branch
        unique_together = ('platform', 'branch')
        table = 'bugreportingplatform'


class ConfigChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    configname = CharField(max_length=100)
    channelid = BigIntField(default=0)

    def __str__(self):
        return str(self.channelid)

    class Meta:
        unique_together = ('configname', 'serverid')
        table = 'configchannel'


class CountWord(AbstractBaseModel, DeprecatedServerIdMixIn):
    # guild = ForeignKeyField(f'{app}.Guild', related_name='watchwords')
    word = CharField(max_length=300)

    def __str__(self):
        return self.word

    class Meta:
        unique_together = ('word', 'serverid')
        table = 'countword'


class CustomCommand(AbstractBaseModel, DeprecatedServerIdMixIn):
    trigger = CharField(max_length=20)
    response = CharField(max_length=2000)
    deletetrigger = BooleanField(default=False)
    reply = BooleanField(default=False)

    def __str__(self):
        return self.trigger

    class Meta:
        unique_together = ('trigger', 'serverid')
        table = 'customcommand'


class DropboxChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    sourcechannelid = BigIntField()
    targetchannelid = BigIntField(default=0)
    deletedelayms = SmallIntField(default=0)
    sendreceipt = BooleanField(default=False)

    def __str__(self):
        return str(self.sourcechannelid)

    class Meta:
        unique_together = ('serverid', 'sourcechannelid')
        table = 'dropboxchannel'


class Guild(AbstractBaseModel):
    serverid = BigIntField(unique=True)
    memberrole = BigIntField(default=0)
    nonmemberrole = BigIntField(default=0)
    mutedrole = BigIntField(default=0)
    betarole = BigIntField(default=0)
    welcomechannelid = BigIntField(default=0)
    ruleschannelid = BigIntField(default=0)
    logchannelid = BigIntField(default=0)
    entrychannelid = BigIntField(default=0)
    maintenancechannelid = BigIntField(default=0)
    rulesreactmessageid = BigIntField(default=0)
    defaultlocale = CharField(max_length=10, default="en_US")

    admin_roles: ReverseRelation["AdminRole"]
    autoresponders: ReverseRelation["AutoResponder"]
    bug_channels: ReverseRelation["BugReportingChannel"]
    locales: ReverseRelation["Localization"]
    mod_roles: ReverseRelation["ModRole"]
    trusted_roles: ReverseRelation["TrustedRole"]
    command_permissions: ReverseRelation["UserPermission"]

    def __str__(self):
        return self.serverid

    class Meta:
        table = 'guild'


class KrillByLines(AbstractBaseModel):
    krill_config = ForeignKeyField(f'{app}.KrillConfig', related_name='bylines', index=True)
    byline = CharField(max_length=100)
    type = SmallIntField(default=0)
    channelid = BigIntField(default=0)
    locale = CharField(max_length=10, default='')

    def __str__(self):
        return self.byline

    class Meta:
        unique_together = ('krill_config', 'byline', 'type')
        table = 'krillbylines'


class KrillChannel(AbstractBaseModel, DeprecatedServerIdMixIn):
    channelid = BigIntField()

    def __str__(self):
        return f"Krillchannel id:{str(self.channelid)}, channelid:{self.channelid}"

    class Meta:
        unique_together = ('serverid', 'channelid')
        table = 'krillchannel'


class KrillConfig(AbstractBaseModel):
    guild = OneToOneField(f'{app}.Guild', related_name='krill_config', index=True)
    return_home_freq = SmallIntField(default=0)
    shadow_roll_freq = SmallIntField(default=0)
    krill_rider_freq = SmallIntField(default=0)
    crab_freq = SmallIntField(default=0)
    allow_text = BooleanField(default=True)
    monster_duration = SmallIntField(default=21600)

    bylines: ReverseRelation["KrillByLines"]

    def __str__(self):
        return self.guild.id

    class Meta:
        table = 'krillconfig'


class Localization(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='locales', index=True)
    channelid = BigIntField(default=0)
    locale = CharField(max_length=10, default='')

    def __str__(self):
        return f"localized channel {str(self.channelid)} uses language: {self.locale}"

    class Meta:
        unique_together = ('guild', 'channelid')
        table = 'localization'


class MischiefRole(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='mischief_roles', index=True)
    roleid = BigIntField()
    alias = CharField(max_length=100)

    def __str__(self):
        return f"role {self.roleid} a.k.a \"{self.alias}\""

    class Meta:
        unique_together = ('roleid', 'guild')
        table = 'mischiefrole'


class ModRole(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='mod_roles', index=True)
    roleid = BigIntField()

    def __str__(self):
        return str(self.roleid)

    class Meta:
        unique_together = ('roleid', 'guild')
        table = 'modrole'


class OreoLetters(AbstractBaseModel):
    token = CharField(max_length=50, default="")
    token_class = SmallIntField()

    def __str__(self):
        return self.token

    class Meta:
        unique_together = ('token', 'token_class')
        table = 'oreoletters'


class OreoMap(AbstractBaseModel):
    letter_o = SmallIntField(default=1)
    letter_r = SmallIntField(default=2)
    letter_e = SmallIntField(default=3)
    letter_oh = SmallIntField(default=4)
    letter_re = SmallIntField(default=5)
    space_char = SmallIntField(default=6)
    char_count = CharField(max_length=50, default="{0,10}")

    def __str__(self):
        return 'enum mapping'

    class Meta:
        table = 'oreomap'


class ReactWatch(AbstractBaseModel):
    # guild = OneToOneField(f'{app}.Guild', related_name='watchemoji')
    serverid = BigIntField(unique=True)
    muteduration = SmallIntField(default=600)
    watchremoves = BooleanField(default=False)

    emoji: ReverseRelation["WatchedEmoji"]

    def __str__(self):
        return f"Server: {self.serverid} - Mute Time: {self.muteduration}s - " \
               f"Watching for react removal: {'YES' if self.watchremoves else 'NO'}"

    class Meta:
        table = 'reactwatch'


class Repros(AbstractBaseModel):
    user = BigIntField()
    report = ForeignKeyField(f'{app}.BugReport', related_name='repros', index=True)

    def __str__(self):
        return f"repro #{self.id} (unused)"

    class Meta:
        unique_together = ('user', 'report')
        table = 'repros'


class TrustedRole(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='trusted_roles', index=True)
    roleid = BigIntField()

    def __str__(self):
        return str(self.roleid)

    class Meta:
        unique_together = ('roleid', 'guild')
        table = 'trustedrole'


class UserPermission(AbstractBaseModel):
    guild = ForeignKeyField(f'{app}.Guild', related_name='command_permissions', index=True)
    userid = BigIntField()
    command = CharField(max_length=200, default='')
    allow = BooleanField(default=True)

    def __str__(self):
        return f"{str(self.userid)}: {self.command} = {'true' if self.allow else 'false'}"

    class Meta:
        unique_together = ('userid', 'command')
        table = 'userpermission'


class WatchedEmoji(AbstractBaseModel):
    watcher = ForeignKeyField(f'{app}.ReactWatch', related_name='emoji', index=True)
    emoji = CharField(max_length=50)
    log = BooleanField(default=False)
    remove = BooleanField(default=False)
    mute = BooleanField(default=False)

    def __str__(self):
        return self.emoji

    class Meta:
        unique_together = ('emoji', 'watcher')
        table = 'watchedemoji'

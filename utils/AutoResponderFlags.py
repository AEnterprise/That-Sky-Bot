from enum import IntFlag
from utils import Utils
from utils.Constants import DISCORD_INDENT


class ArFlags(IntFlag):
    ACTIVE = 1 << 0
    FULL_MATCH = 1 << 1
    DELETE = 1 << 2
    MATCH_CASE = 1 << 3
    IGNORE_MOD = 1 << 4
    MOD_ACTION = 1 << 5
    LOG_ONLY = 1 << 6
    DM_RESPONSE = 1 << 7
    DELETE_WHEN_TRIGGER_DELETED = 1 << 8
    DELETE_ON_MOD_RESPOND = 1 << 9
    USE_REPLY = 1 << 10

    def __str__(self):
        flags = []
        for i in ArFlags:
            if i in self:
                flags.append(i.name.lower())
        return ", ".join(flags)

    @staticmethod
    def init_by_bitshift(value: int):
        if not ArFlags.bitshift_is_valid_flag(value):
            raise ValueError
        return ArFlags(1 << value)

    @staticmethod
    def get_name_by_bitshift(value: int):
        flag = ArFlags.init_by_bitshift(value)
        return flag.name.lower()

    @staticmethod
    def get_all_names():
        return [i.name.lower() for i in ArFlags]

    @staticmethod
    def bitshift_is_valid_flag(value: int) -> bool:
        return value >= 0 and Utils.is_power_of_two(1 << value) and 1 << value in [int(i) for i in ArFlags]

    def get_flags_description(self, pre=None) -> str:
        """Flag formatting for standardization in dialogs

        Parameters
        ----------
        pre: str
            some empty space for indent, if a prefix string is not given

        Returns
        -------
        str
            Description of which flags are set, or "DISABLED" if not active
        """
        #
        pre = pre or DISCORD_INDENT
        if ArFlags.ACTIVE in self:
            return f'{pre} Flags: **{self}**'
        return f"{pre} ***DISABLED***"

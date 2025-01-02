import os
import shutil
import time
import pipes
from utils import tortoise_settings as ts, Logging
from utils.Logging import TCol


def backup_database():
    max_backups = 15
    Logging.info("Database Backup", TCol.Cyan)
    base_path = './backup/database/'
    backup_path = base_path + time.strftime('%Y%m%d_%H')

    # Alternate filename could include minutes and seconds to allow more frequent backups
    # backup_path = base_path + time.strftime('%Y%m%d_%H%M%S')

    # If the given backup dir exists, stop. Filename limits backups to one per hour
    try:
        Logging.info("\tbackup_database: check for backup folder")
        os.stat(backup_path)
        Logging.info("\trecent backup exists. skipping.")
        return
    except OSError:
        # dir does not exist. create it and continue
        Logging.info("\tbackup_database: create backup folder")
        try:
            os.makedirs(backup_path)
        except FileExistsError:
            pass

    Logging.info(f"\tstarting backup of database {ts.db_name}")

    # username and password are not included, for security.
    # This assumes a .my.cnf exists with mysqldump credentials:
    # [mysqldump]
    # user=your_username
    # password=your_password
    dump_command = f"mysqldump -h {ts.db_host} {ts.db_name} > " + \
                   f"{pipes.quote(backup_path)}/{ts.db_name}.sql"

    # do the backup
    os.system(dump_command)
    # backup config and persistent as well
    shutil.copy2('config.json', backup_path)
    shutil.copy2('persistent.json', backup_path)

    to_zip = [
        f"{pipes.quote(backup_path)}/{ts.db_name}.sql",
        f"{pipes.quote(backup_path)}/config.json",
        f"{pipes.quote(backup_path)}/persistent.json"
    ]
    # zip the backups
    for zip_path in to_zip:
        os.system(f"gzip {zip_path}")

    # get rid of old backups
    count = 0
    # List backup dirs in descending order.
    ll = os.listdir(base_path)
    ll.sort(reverse=True)
    Logging.info("\tExisting backups:")
    for directory in ll:
        this_dir = os.path.join(base_path, directory)
        if os.path.isdir(this_dir):
            count += 1
            if count > max_backups:
                # delete an old backup
                shutil.rmtree(this_dir, ignore_errors=True)
                Logging.info(f"\tremoving old backup {this_dir}", TCol.Warning)
            else:
                Logging.info(f"\t{this_dir}")

    Logging.info(f"\tdatabase {ts.db_name} backed up in '{backup_path}'")
    Logging.info("\tDatabase Backup Complete", TCol.Green)

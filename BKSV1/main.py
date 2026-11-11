from pathlib import Path
from database import BackupDatabase
from gui import PasarelaApp


def main():
    database = BackupDatabase(Path.cwd() / 'pasarela_backups.db')
    PasarelaApp(database).mainloop()


if __name__ == '__main__':
    main()

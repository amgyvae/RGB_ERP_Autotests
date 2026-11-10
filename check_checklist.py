"""Check Google Sheets connection; --write-check verifies a temporary cell note."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
for directory in (ROOT,ROOT/'core',ROOT/'config'):
    sys.path.insert(0,str(directory))
from sheet_reporter import _connect,HEADER_ROW,COL_TASK

def main():
    try:
        ws=_connect()
        headers=ws.row_values(HEADER_ROW)
        tasks=ws.col_values(COL_TASK)
        if not headers or not any(tasks):
            raise RuntimeError('Нет заголовков или названий проверок на выбранном листе')
        print('Чтение OK:',ws.spreadsheet.title,'/',ws.title)
        if '--write-check' in sys.argv:
            import uuid
            cell=ws.cell(HEADER_ROW,COL_TASK)
            address=cell.address
            original=ws.get_note(address) or ''
            marker='Проверка автозаписи '+uuid.uuid4().hex
            try:
                ws.update_note(address,marker)
                if ws.get_note(address)!=marker:
                    raise RuntimeError('Запись примечания не подтверждена чтением')
            finally:
                ws.update_note(address,original)
            print('Запись и контрольное чтение OK; исходное примечание восстановлено. Статусы тестов не изменены.')
        else:
            print('Для проверки права записи: py check_checklist.py --write-check')
        return 0
    except Exception as exc:
        print('Google Sheets ERROR:',type(exc).__name__,str(exc))
        return 2
if __name__=='__main__':
    raise SystemExit(main())

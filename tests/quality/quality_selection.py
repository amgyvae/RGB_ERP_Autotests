"""Shared scope for explicitly requested reruns of recently repaired quality scenarios."""
FIXED_QUALITY_CHECKS=(
    'Вход и открытие раздела «Контроль качества»',
    'Предписания: отбор, поиск и навигация по реестру',
    'Предписания: зависимые поля, ограничения ввода и отмена формы',
    'Предписания: сохранение черновика и продолжение публикации',
    'Предписания: создание, данные карточки, документы и обсуждение',
    'Предписания: назначение участника и обязательные данные исполнения',
    'Предписания: исполнение, возврат и завершение по ролям',
    'Предписания: завершённая запись — повторные действия и сохранение в реестре',
)

def fixed_only(args):
    return '--only-fixed' in args

def selected_quality_checks(checks,args):
    if not fixed_only(args):return checks
    if list(args)!=['--only-fixed']:
        raise ValueError('Для выборочного запуска используйте только --only-fixed')
    missing=set(FIXED_QUALITY_CHECKS)-set(checks)
    if missing:raise ValueError('Исправленные сценарии отсутствуют в перечне: '+', '.join(sorted(missing)))
    return list(FIXED_QUALITY_CHECKS)

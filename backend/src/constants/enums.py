ROLES=('admin','analyst','viewer')
REPORT_STATUSES=('queued','running','completed','failed')
GROUPS=('control','intervention')
IMPORT_SOURCES=('enrollment','exam')
BATCH_STATUSES=('pending','processing','completed','failed')
ROW_DECISIONS=('added','revised','stale','quarantined','duplicate')
# 每种来源只允许合并自己管辖的字段：学籍不动成绩，考试不动分组
SOURCE_FIELDS={'enrollment':('name','campus','group'),'exam':('score','absent')}
SOURCE_LABELS={'enrollment':'学籍','exam':'考试'}

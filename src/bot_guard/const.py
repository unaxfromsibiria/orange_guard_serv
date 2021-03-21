HELP_MSG = """Commands:
/adduser <username or id> - add telegram user
/deluser <username or id> - delete access for telegram user
/temp <begin date> <end date or empity> - temperature in period [begin..end] or [begin..now]
/events <on/off> - add/remove me to events subscription
/photo - get photo at this moment
/start <air/light/alarm/engine> <time in minutes default 10 min> - on GPIO group
/off <air/light/alarm/engine> - off GPIO group
/air-time <time begin>-<time end> <time begin>-<time end> ... - schedule for 'air' GPIO group
/restart - restart web-api server (a problem solving case)
/help - see this message again
"""

NOT_ACCESS_ERROR = "Access denied"

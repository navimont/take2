"""Miscellaneous helper functions"""

import calendar
from datetime import datetime

def prepare_birthday_selectors():
    """Prepare the lists of days and month which are needed to enter a valid birthday"""

    # prepare list of days and months
    daylist = ["(skip)"]
    daylist.extend([str(day) for day in range(1,32)])
    monthlist=[(str(i),calendar.month_name[i]) for i in range(13)]
    monthlist[0] = ("0","(skip)")
    yearlist = ["(skip)"]
    yearlist.extend([str(year) for year in range(datetime.today().year,datetime.today().year-120,-1)])

    return {'daylist': daylist, 'monthlist': monthlist, 'yearlist': yearlist}

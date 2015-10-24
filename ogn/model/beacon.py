from datetime import *
import re

from sqlalchemy import Column, String, Integer, Float, DateTime
from sqlalchemy.ext.declarative import AbstractConcreteBase

from ogn.aprs_utils import *
from ogn.model.base import Base


# "original" pattern from OGN: "(.+?)>APRS,.+,(.+?):/(\\d{6})+h(\\d{4}\\.\\d{2})(N|S).(\\d{5}\\.\\d{2})(E|W).((\\d{3})/(\\d{3}))?/A=(\\d{6}).*?"
PATTERN_APRS = r"^(.+?)>APRS,.+,(.+?):/(\d{6})+h(\d{4}\.\d{2})(N|S)(.)(\d{5}\.\d{2})(E|W)(.)((\d{3})/(\d{3}))?/A=(\d{6})\s(.*)$"
prog = re.compile(PATTERN_APRS)


class Beacon(AbstractConcreteBase, Base):
    id = Column(Integer, primary_key=True)

    # APRS data
    name = Column(String)
    receiver_name = Column(String(9))
    timestamp = Column(DateTime, index=True)
    latitude = Column(Float)
    symboltable = None
    longitude = Column(Float)
    symbolcode = None
    ground_speed = Column(Float)
    track = Column(Integer)
    altitude = Column(Integer)
    comment = None

    def parse(self, text, reference_time=None):
        result = prog.match(text)
        if result is None:
            raise Exception("String is not valid" % text)

        self.name = result.group(1)
        self.receiver_name = result.group(2)

        self.timestamp = createTimestamp(result.group(3), reference_time)

        self.latitude = dmsToDeg(float(result.group(4)) / 100)
        if result.group(5) == "S":
            self.latitude = -self.latitude

        self.symboltable = result.group(6)

        self.longitude = dmsToDeg(float(result.group(7)) / 100)
        if result.group(8) == "W":
            self.longitude = -self.longitude

        self.symbolcode = result.group(9)

        if result.group(10) is not None:
            self.ground_speed = int(result.group(11))*kts2kmh
            self.track = int(result.group(12))
        else:
            self.speed = 0
            self.track = 0

        self.altitude = int(result.group(13))*feet2m

        self.comment = result.group(14)
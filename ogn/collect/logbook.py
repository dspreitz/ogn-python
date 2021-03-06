from celery.utils.log import get_task_logger

from sqlalchemy import and_, or_, insert, update, between, exists
from sqlalchemy.sql import func, null
from sqlalchemy.sql.expression import true, false, label

from ogn.collect.celery import app
from ogn.model import TakeoffLanding, Logbook

logger = get_task_logger(__name__)


@app.task
def compute_logbook_entries(session=None):
    logger.info("Compute logbook.")

    if session is None:
        session = app.session

    or_args = [between(TakeoffLanding.timestamp, '2016-06-28 00:00:00', '2016-06-28 23:59:59')]
    or_args = []

    # 'wo' is the window order for the sql window function
    wo = and_(func.date(TakeoffLanding.timestamp),
              TakeoffLanding.device_id,
              TakeoffLanding.timestamp,
              TakeoffLanding.airport_id)

    # make a query with current, previous and next "takeoff_landing" event, so we can find complete flights
    sq = session.query(
            TakeoffLanding.device_id,
            func.lag(TakeoffLanding.device_id).over(order_by=wo).label('device_id_prev'),
            func.lead(TakeoffLanding.device_id).over(order_by=wo).label('device_id_next'),
            TakeoffLanding.timestamp,
            func.lag(TakeoffLanding.timestamp).over(order_by=wo).label('timestamp_prev'),
            func.lead(TakeoffLanding.timestamp).over(order_by=wo).label('timestamp_next'),
            TakeoffLanding.track,
            func.lag(TakeoffLanding.track).over(order_by=wo).label('track_prev'),
            func.lead(TakeoffLanding.track).over(order_by=wo).label('track_next'),
            TakeoffLanding.is_takeoff,
            func.lag(TakeoffLanding.is_takeoff).over(order_by=wo).label('is_takeoff_prev'),
            func.lead(TakeoffLanding.is_takeoff).over(order_by=wo).label('is_takeoff_next'),
            TakeoffLanding.airport_id,
            func.lag(TakeoffLanding.airport_id).over(order_by=wo).label('airport_id_prev'),
            func.lead(TakeoffLanding.airport_id).over(order_by=wo).label('airport_id_next')) \
        .filter(*or_args) \
        .subquery()

    # find complete flights (with takeoff and landing on the same day)
    complete_flight_query = session.query(
            sq.c.timestamp.label('reftime'),
            sq.c.device_id.label('device_id'),
            sq.c.timestamp.label('takeoff_timestamp'), sq.c.track.label('takeoff_track'), sq.c.airport_id.label('takeoff_airport_id'),
            sq.c.timestamp_next.label('landing_timestamp'), sq.c.track_next.label('landing_track'), sq.c.airport_id_next.label('landing_airport_id'),
            label('duration', sq.c.timestamp_next - sq.c.timestamp)) \
        .filter(and_(sq.c.is_takeoff == true(), sq.c.is_takeoff_next == false())) \
        .filter(sq.c.device_id == sq.c.device_id_next) \
        .filter(func.date(sq.c.timestamp_next) == func.date(sq.c.timestamp))

    # split complete flights (with takeoff and landing on different days) into one takeoff and one landing
    split_start_query = session.query(
            sq.c.timestamp.label('reftime'),
            sq.c.device_id.label('device_id'),
            sq.c.timestamp.label('takeoff_timestamp'), sq.c.track.label('takeoff_track'), sq.c.airport_id.label('takeoff_airport_id'),
            null().label('landing_timestamp'), null().label('landing_track'), null().label('landing_airport_id'),
            null().label('duration')) \
        .filter(and_(sq.c.is_takeoff == true(), sq.c.is_takeoff_next == false())) \
        .filter(sq.c.device_id == sq.c.device_id_next) \
        .filter(func.date(sq.c.timestamp_next) != func.date(sq.c.timestamp))

    split_landing_query = session.query(
            sq.c.timestamp_next.label('reftime'),
            sq.c.device_id.label('device_id'),
            null().label('takeoff_timestamp'), null().label('takeoff_track'), null().label('takeoff_airport_id'),
            sq.c.timestamp_next.label('landing_timestamp'), sq.c.track_next.label('landing_track'), sq.c.airport_id_next.label('landing_airport_id'),
            null().label('duration')) \
        .filter(and_(sq.c.is_takeoff == true(), sq.c.is_takeoff_next == false())) \
        .filter(sq.c.device_id == sq.c.device_id_next) \
        .filter(func.date(sq.c.timestamp_next) != func.date(sq.c.timestamp))

    # find landings without start
    only_landings_query = session.query(
            sq.c.timestamp.label('reftime'),
            sq.c.device_id.label('device_id'),
            null().label('takeoff_timestamp'), null().label('takeoff_track'), null().label('takeoff_airport_id'),
            sq.c.timestamp.label('landing_timestamp'), sq.c.track.label('landing_track'), sq.c.airport_id.label('landing_airport_id'),
            null().label('duration')) \
        .filter(sq.c.is_takeoff == false()) \
        .filter(or_(sq.c.device_id != sq.c.device_id_prev,
                    sq.c.is_takeoff_prev == false(),
                    sq.c.is_takeoff_prev == null()))

    # find starts without landing
    only_starts_query = session.query(
            sq.c.timestamp.label('reftime'),
            sq.c.device_id.label('device_id'),
            sq.c.timestamp.label('takeoff_timestamp'), sq.c.track.label('takeoff_track'), sq.c.airport_id.label('takeoff_airport_id'),
            null().label('landing_timestamp'), null().label('landing_track'), null().label('landing_airport_id'),
            null().label('duration')) \
        .filter(sq.c.is_takeoff == true()) \
        .filter(or_(sq.c.device_id != sq.c.device_id_next,
                    sq.c.is_takeoff_next == true(),
                    sq.c.is_takeoff_next == null()))

    # unite all computated flights
    union_query = complete_flight_query.union(
            split_start_query,
            split_landing_query,
            only_landings_query,
            only_starts_query) \
        .subquery()

    # if a logbook entry exist --> update it
    upd = update(Logbook) \
        .where(and_(Logbook.device_id == union_query.c.device_id,
                    union_query.c.takeoff_airport_id != null(),
                    union_query.c.landing_airport_id != null(),
                    or_(and_(Logbook.takeoff_airport_id == union_query.c.takeoff_airport_id,
                             Logbook.takeoff_timestamp == union_query.c.takeoff_timestamp,
                             Logbook.landing_airport_id == null()),
                        and_(Logbook.takeoff_airport_id == null(),
                             Logbook.landing_airport_id == union_query.c.landing_airport_id,
                             Logbook.landing_timestamp == union_query.c.landing_timestamp)))) \
        .values({"takeoff_timestamp": union_query.c.takeoff_timestamp,
                 "takeoff_track": union_query.c.takeoff_track,
                 "takeoff_airport_id": union_query.c.takeoff_airport_id,
                 "landing_timestamp": union_query.c.landing_timestamp,
                 "landing_track": union_query.c.landing_track,
                 "landing_airport_id": union_query.c.landing_airport_id,
                 "duration": union_query.c.duration})

    result = session.execute(upd)
    update_counter = result.rowcount
    session.commit()
    logger.debug("Updated logbook entries: {}".format(update_counter))

    # if a logbook entry doesnt exist --> insert it
    new_logbook_entries = session.query(union_query) \
        .filter(~exists().where(
            and_(Logbook.device_id == union_query.c.device_id,
                 or_(and_(Logbook.takeoff_airport_id == union_query.c.takeoff_airport_id,
                          Logbook.takeoff_timestamp == union_query.c.takeoff_timestamp),
                     and_(Logbook.takeoff_airport_id == null(),
                          union_query.c.takeoff_airport_id == null())),
                 or_(and_(Logbook.landing_airport_id == union_query.c.landing_airport_id,
                          Logbook.landing_timestamp == union_query.c.landing_timestamp),
                     and_(Logbook.landing_airport_id == null(),
                          union_query.c.landing_airport_id == null())))))

    ins = insert(Logbook).from_select((Logbook.reftime,
                                       Logbook.device_id,
                                       Logbook.takeoff_timestamp,
                                       Logbook.takeoff_track,
                                       Logbook.takeoff_airport_id,
                                       Logbook.landing_timestamp,
                                       Logbook.landing_track,
                                       Logbook.landing_airport_id,
                                       Logbook.duration),
                                      new_logbook_entries)

    result = session.execute(ins)
    insert_counter = result.rowcount
    session.commit()
    logger.debug("New logbook entries: {}".format(insert_counter))

    return "{}/{}".format(update_counter, insert_counter)

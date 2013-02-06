"""
Database request handler for x/84 http://github.com/jquast/x84
"""
import x84.bbs.exception
import x84.bbs.ini
import threading
import logging
import os
import sqlitedict
# pylint: disable=C0103
#        Invalid name "logger" for type constant
logger = logging.getLogger(__name__)

FILELOCK = threading.Lock()


class DBHandler(threading.Thread):
    """
    This handler receives a "database command", in the form of a dictionary
    method name and its arguments, and the return value is sent to the session
    pipe with the same 'event' name.
    """

    # pylint: disable=R0902
    #        Too many instance attributes (8/7)
    def __init__(self, pipe, event, data):
        """ Arguments:
              pipe: parent end of multiprocessing.Pipe()
              event: database schema in form of string 'db-schema' or
                  'db=schema'. When '-' is used, the result is returned as a
                  single transfer. When '=', an iterable is yielded and the
                  data is transfered via the IPC pipe as a stream.
        """
        self.pipe = pipe
        self.event = event
        assert event[2] in ('-', '='), ('event name must match db[-=]event')
        self.iterable = event[2] == '='
        self.schema = event[3:]
        assert self.schema.isalnum() and os.path.sep not in self.schema, (
            'database schema "%s" must be alpha-numeric and not contain %s' % (
                self.schema, os.path.sep,))
        self.table = data[0]
        self.cmd = data[1]
        self.args = data[2]
        folder = x84.bbs.ini.CFG.get('system', 'datapath')
        self.filepath = os.path.join(folder, '%s.sqlite3' % (self.schema,),)
        threading.Thread.__init__(self)

    def run(self):
        """
        Execute database command and return results to session pipe.
        """

        FILELOCK.acquire()
        if not os.path.exists(os.path.dirname(self.filepath)):
            os.makedirs(os.path.dirname(self.filepath))
        dictdb = sqlitedict.SqliteDict(
            filename=self.filepath, tablename=self.table, autocommit=True)
        FILELOCK.release()
        assert hasattr(dictdb, self.cmd), (
            "'%(cmd)s' not a valid method of <type 'dict'>" % self)
        func = getattr(dictdb, self.cmd)
        assert callable(func), (
            "'%(cmd)s' not a valid method of <type 'dict'>" % self)
        logger.debug('%s/%s%s', self.schema, self.cmd,
                     '(*%d)' % (len(self.args)) if len(self.args) else '()')

        # single value result,
        if not self.iterable:
            try:
                if 0 == len(self.args):
                    result = func()
                else:
                    result = func(*self.args)
            # pylint: disable=W0703
            #         Catching too general exception
            except Exception as err:
                # Pokemon exception; package & raise from session process,
                self.pipe.send(('exception', err,))
                dictdb.close()
                logger.exception(err)
                return
            self.pipe.send((self.event, result))
            dictdb.close()
            return

        # iterable value result,
        self.pipe.send((self.event, (None, 'StartIteration'),))
        try:
            if 0 == len(self.args):
                for item in func():
                    self.pipe.send((self.event, item,))
            else:
                for item in func(*self.args):
                    self.pipe.send((self.event, item,))
        # pylint: disable=W0703
        #         Catching too general exception
        except Exception as err:
            # Pokemon exception; package & raise from session process,
            self.pipe.send(('exception', err,))
            dictdb.close()
            logger.exception(err)
            return

        self.pipe.send((self.event, (None, StopIteration,),))
        dictdb.close()
        return

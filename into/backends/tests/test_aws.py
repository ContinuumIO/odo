import pytest
import os
from into import into, resource, S3, discover, CSV, drop
from into.utils import tmpfile
import pandas as pd
import pandas.util.testing as tm
import datashape

sa = pytest.importorskip('sqlalchemy')
pytest.importorskip('psycopg2')
pytest.importorskip('redshift_sqlalchemy')


tips_uri = 's3://nyqpug/tips.csv'


def test_s3_resource():
    csv = resource(tips_uri)
    assert isinstance(csv, S3(CSV))


def test_s3_discover():
    csv = resource(tips_uri)
    assert isinstance(discover(csv), datashape.DataShape)


def test_s3_to_local_csv():
    with tmpfile('.csv') as fn:
        csv = into(fn, tips_uri)
        path = os.path.abspath(csv.path)
        assert os.path.exists(path)


@pytest.fixture
def db():
    try:
        return os.environ['REDSHIFT_DB_URI']
    except KeyError:
        pytest.skip('Please define an environment variable called '
                    'REDSHIFT_DB_URI to test redshift <- S3')


@pytest.mark.xfail(raises=IOError, reason='not implemented yet')
def test_frame_to_s3():
    df = pd.DataFrame({
        'a': list('abc'),
        'b': [1, 2, 3],
        'c': [1.0, 2.0, 3.0]
    })[['a', 'b', 'c']]

    to_this = S3(CSV)('s3://nyqpug/test.csv')
    s3_csv = into(to_this, df)
    result = into(pd.DataFrame, s3_csv)
    tm.assert_frame_equal(result, df)


def test_s3_to_redshift(db):
    redshift_uri = '%s::tips' % db
    s3 = S3(CSV)('s3://nyqpug/tips.csv')
    table = into(redshift_uri, s3, dshape=discover(s3))
    dshape = discover(table)
    ds = datashape.dshape("""
    var * {
        total_bill: float64,
        tip: float64,
        sex: string,
        smoker: string,
        day: string,
        time: string,
        size: int64
    }""")
    try:
        # make sure our table is properly named
        assert table.name == 'tips'

        # make sure we have a non empty table
        assert table.bind.execute("select count(*) from tips;").scalar() == 244

        # make sure we have the proper column types
        assert dshape == ds
    finally:
        # don't hang around
        drop(table)


def test_redshift_getting_started(db):
    dshape = datashape.dshape("""var * {
        userid: int64,
        username: ?string[8],
        firstname: ?string[30],
        lastname: ?string[30],
        city: ?string[30],
        state: ?string[2],
        email: ?string[100],
        phone: ?string[14],
        likesports: ?bool,
        liketheatre: ?bool,
        likeconcerts: ?bool,
        likejazz: ?bool,
        likeclassical: ?bool,
        likeopera: ?bool,
        likerock: ?bool,
        likevegas: ?bool,
        likebroadway: ?bool,
        likemusicals: ?bool,
    }""")

    redshift_uri = '%s::users' % db
    csv = S3(CSV)('s3://awssampledb/tickit/allusers_pipe.txt')
    table = into(redshift_uri, csv, dshape=dshape, delimiter='|')
    try:
        # make sure our table is properly named
        assert table.name == 'users'

        # make sure we have a non empty table
        assert table.bind.execute("select count(*) from users;").scalar() == 49989
    finally:
        # don't hang around
        drop(table)
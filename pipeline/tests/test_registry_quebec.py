import io
import zipfile

from lmia_pipeline.db import get_meta, upsert_employer
from lmia_pipeline.sources import registry_quebec

# Column subsets of the publisher's files; the parser reads columns by name.
ENTREPRISE = (
    "﻿NEQ,IND_FAIL,DAT_IMMAT,COD_REGIM_JURI,COD_STAT_IMMAT,COD_FORME_JURI,DAT_STAT_IMMAT,"
    "ADR_DOMCL_ADR_DISP,ADR_DOMCL_LIGN1_ADR,ADR_DOMCL_LIGN2_ADR,ADR_DOMCL_LIGN3_ADR,ADR_DOMCL_LIGN4_ADR\r\n"
    "1160000001,N,2004-05-10,024,IM,CIE,2004-05-10,N,4326 rue Rivard,Montréal (Québec),,H2J2M8\r\n"
    "1160000002,N,1999-09-08,,RO,SENC,2016-05-31,N,143A BELZILE,RIMOUSKI QC,,G5L3E5\r\n"
    "1160000003,N,1990-01-01,,RD,CIE,2005-02-01,N,1 rue Vieille,Québec (Québec),,G1R2N1\r\n"
    "2260000004,N,2010-03-03,,IM,IND,2010-03-03,N,,,,\r\n"
    "1160000005,N,2015-06-01,024,IM,CIE,2015-06-01,N,100 King Street West,Toronto (Ontario),,M5X1A9\r\n"
    "1160000006,N,2020-01-15,024,IM,CIE,2020-01-15,N,5 rue du Port,Gaspé (Québec),,G4X1A1\r\n"
)
NOM = (
    "﻿NEQ,NOM_ASSUJ,NOM_ASSUJ_LANG_ETRNG,STAT_NOM,TYP_NOM_ASSUJ,DAT_INIT_NOM_ASSUJ,DAT_FIN_NOM_ASSUJ\r\n"
    "1160000001,9123-4567 QUÉBEC INC.,,V,M,2004-05-10,\r\n"
    "1160000001,Garage Pépin,,V,A,2004-05-10,\r\n"
    "1160000001,Ancien Garage,,A,A,2004-05-10,2015-01-01\r\n"
    # Struck off: the names in force on the day of the strike-off count, an older one does not.
    "1160000002,FERME CÉLIJEAN S.E.N.C.,,A,N,1999-09-08,2016-05-31\r\n"
    "1160000002,Les Jardins Célijean,,A,A,2001-01-01,2016-05-31\r\n"
    "1160000002,FERME ANCIENNE S.E.N.C.,,A,N,1990-01-01,2014-01-01\r\n"
    "1160000003,VIEILLE COMPAGNIE INC.,,A,N,1990-01-01,2005-02-01\r\n"
    "2260000004,Jean Exemple,,V,N,2010-03-03,\r\n"
    "1160000005,LES INVESTISSEMENTS MARIALEX INC.,MARIALEX INVESTMENTS INC.,V,N,2015-06-01,\r\n"
    "1160000006,PÊCHERIES DU PORT INC.,,V,N,2020-01-15,\r\n"
    "1160000006,PECHERIES DU PORT INC,,V,A,2020-01-15,\r\n"
)
NOW = "2026-10-17T00:00:00Z"


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("Entreprise.csv", ENTREPRISE.encode("utf-8"))
        zf.writestr("Nom.csv", NOM.encode("utf-8"))
        zf.writestr("DomaineValeur.csv", b"TYP_DOM_VAL,COD_DOM_VAL,VAL_DOM_FRAN\r\n")
    return buf.getvalue()


def test_parse_keeps_names_in_force_and_skips_sole_proprietors():
    rows = registry_quebec.parse_extract(make_zip())
    by_name = {r[1]: r for r in rows}
    garage = by_name["9123-4567 QUÉBEC INC."]
    assert garage[:4] == ("1160000001", "9123-4567 QUÉBEC INC.", "9123 4567 quebec", "legal")
    assert garage[4:] == ("9123-4567 QUÉBEC INC.", "Active", "CIE", "2004-05-10", "H2J 2M8", "QC")
    assert by_name["Garage Pépin"][2:5] == ("garage pepin", "other", "9123-4567 QUÉBEC INC.")
    assert "Ancien Garage" not in by_name                       # a former name of a registered enterprise
    assert "Jean Exemple" not in by_name                        # a sole proprietorship
    assert "VIEILLE COMPAGNIE INC." not in by_name              # struck off before 2012
    assert "FERME ANCIENNE S.E.N.C." not in by_name             # no longer in force when struck off
    ferme = by_name["FERME CÉLIJEAN S.E.N.C."]
    assert ferme[3] == "legal" and ferme[5] == "Struck off" and ferme[9] == "QC"
    assert by_name["Les Jardins Célijean"][4] == "FERME CÉLIJEAN S.E.N.C."
    assert by_name["MARIALEX INVESTMENTS INC."][3] == "legal"   # the other-language version of the legal name
    assert by_name["LES INVESTISSEMENTS MARIALEX INC."][9] == "ON"
    # An other name that normalizes like the legal name is not stored twice.
    assert [r[1] for r in rows if r[0] == "1160000006"] == ["PÊCHERIES DU PORT INC."]


def test_parse_keeps_only_wanted_names():
    rows = registry_quebec.parse_extract(make_zip(), {"garage pepin"})
    assert [(r[1], r[4]) for r in rows] == [("Garage Pépin", "9123-4567 QUÉBEC INC.")]


def test_load_weekly_and_match(conn, fake_client):
    numbered = upsert_employer(conn, "9123-4567 Quebec Inc", "QC", source="esdc_positive", now=NOW)
    trade = upsert_employer(conn, "Garage Pepin", "QC", source="jobbank", now=NOW)
    ferme = upsert_employer(conn, "Ferme Celijean", "QC", source="esdc_positive", now=NOW)
    elsewhere = upsert_employer(conn, "Les Investissements Marialex Inc.", "QC", source="esdc_positive",
                                postal_code="H3A 1R6", now=NOW)
    ontario = upsert_employer(conn, "Pêcheries du Port Inc.", "ON", source="esdc_positive", now=NOW)
    client = fake_client({registry_quebec.URL: make_zip()})

    assert registry_quebec.match(conn, now=NOW) == 0        # nothing loaded yet
    assert registry_quebec.run(conn, client, now=NOW) == 4
    rows = {r["employer_id"]: r for r in conn.execute("SELECT * FROM registry_matches WHERE registry = 'quebec_req'")}
    assert rows[numbered]["grade"] == "exact" and rows[numbered]["registry_id"] == "1160000001"
    assert rows[numbered]["registered_on"] == "2004-05-10" and rows[numbered]["entity_type"] == "CIE"
    assert rows[trade]["grade"] == "probable" and rows[trade]["legal_name"] == "9123-4567 QUÉBEC INC."
    assert rows[ferme]["grade"] == "exact" and rows[ferme]["status"] == "Struck off"
    # Domicile in Ontario and a different postal code: the name alone is probable.
    assert rows[elsewhere]["grade"] == "probable"
    assert ontario not in rows
    # Only names that could match were kept.
    assert conn.execute("SELECT COUNT(*) FROM quebec_enterprises").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM registry_checks WHERE registry = 'quebec_req'").fetchone()[0] == 4
    assert get_meta(conn, registry_quebec.LOADED_KEY) == NOW

    # Within a week nothing is downloaded again; after a week it is.
    calls = len(client.fake_session.calls)
    assert registry_quebec.load_extract(conn, client, now="2026-10-20T00:00:00Z") is None
    assert len(client.fake_session.calls) == calls
    assert registry_quebec.load_extract(conn, client, now="2026-10-25T00:00:00Z") == 4
    assert len(client.fake_session.calls) == calls + 1

    # A normalization change empties the table and forces a load on the next run.
    assert registry_quebec.renormalize(conn) == 4
    assert get_meta(conn, registry_quebec.LOADED_KEY) is None
    assert registry_quebec.load_extract(conn, client, now="2026-10-26T00:00:00Z") == 4

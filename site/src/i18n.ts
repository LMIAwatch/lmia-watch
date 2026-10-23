// Every user-visible string on the site, in English and French, in one place.
// Pages render them with t(lang, key); a {name} in a string is filled from
// the vars argument, and tj() fills a slot with markup (a link inside a
// sentence). The client scripts get the strings they need through a JSON
// block rendered by the page (clientStrings), so they hold no copy of their
// own.
//
// French strings are written with plain spaces and straight apostrophes; the
// typography pass in frTypography() turns them into the Canadian French forms
// when they are read: a no-break space before : % $ and inside « », and the
// typographic apostrophe. English is returned exactly as written.

export type Lang = "en" | "fr";

type Entry = { en: string; fr: string };

const STRINGS = {
  // -- site, navigation, footer ----------------------------------------------
  "site.name": { en: "LMIA Watch", fr: "LMIA Watch" },
  "site.tagline": {
    en: "Public records of Labour Market Impact Assessments",
    fr: "Dossiers publics des études d'impact sur le marché du travail",
  },
  "nav.main_label": { en: "Main", fr: "Navigation principale" },
  "nav.search": { en: "Search", fr: "Recherche" },
  "nav.map": { en: "Map", fr: "Carte" },
  "nav.occupations": { en: "Occupations", fr: "Professions" },
  "nav.places": { en: "Places", fr: "Lieux" },
  "nav.releases": { en: "Releases", fr: "Publications" },
  "nav.methodology": { en: "Methodology", fr: "Méthodologie" },
  "nav.data": { en: "Data & About", fr: "Données et à propos" },
  "nav.support": { en: "Support", fr: "Soutenir" },
  "nav.lang": { en: "FR", fr: "EN" },
  "nav.dark": { en: "Dark", fr: "Sombre" },
  "nav.light": { en: "Light", fr: "Clair" },
  "nav.data_as_of": { en: "Data as of", fr: "Données au" },
  "footer.sources": {
    en: "Sources: Job Bank (ESDC); TFWP positive and negative LMIA employer lists (Open Government Licence, Canada); IRCC non-compliant employers; BC Registry; Corporations Canada; Registraire des entreprises du Québec (CC BY-NC-SA 4.0).",
    fr: "Sources : Guichet-Emplois (EDSC); listes des employeurs ayant reçu une EIMT positive ou négative du PTET (Licence du gouvernement ouvert, Canada); employeurs jugés non conformes (IRCC); BC Registry (registre des entreprises de la Colombie-Britannique); Corporations Canada; Registraire des entreprises du Québec (CC BY-NC-SA 4.0).",
  },
  "footer.download": { en: "Download the Data", fr: "Télécharger les données" },
  "footer.watchlist": { en: "Watchlist", fr: "Liste de suivi" },
  "footer.feeds": { en: "Feeds", fr: "Fils" },
  "footer.corrections": { en: "Corrections", fr: "Corrections" },
  "footer.support": { en: "Support the Site", fr: "Soutenir le site" },
  "footer.x": { en: "LMIA Watch on X", fr: "LMIA Watch sur X" },
  "footer.bluesky": { en: "LMIA Watch on Bluesky", fr: "LMIA Watch sur Bluesky" },
  "footer.copyright": { en: "© 2026 LMIA Watch", fr: "© 2026 LMIA Watch" },
  "search.placeholder": { en: "Employer, city, postal code or occupation", fr: "Employeur, ville, code postal ou profession" },
  "search.button": { en: "Search", fr: "Rechercher" },
  "toc.label": { en: "On this page", fr: "Sur cette page" },
  "toc.title": { en: "On This Page", fr: "Sur cette page" },

  // -- shared words and formats ------------------------------------------------
  "common.na": { en: "n/a", fr: "s.o." },
  "common.home": { en: "Home", fr: "Accueil" },
  "common.back": { en: "Back", fr: "Retour" },
  "common.downloads_link": { en: "downloads", fr: "téléchargements" },
  "common.yes": { en: "yes", fr: "oui" },
  "common.no": { en: "no", fr: "non" },
  "common.no_records": { en: "No records.", fr: "Aucun dossier." },
  "common.see_posting": { en: "see posting", fr: "voir l'offre" },
  "period.quarter": { en: "{y} Q{q}", fr: "T{q} {y}" },
  "period.range": { en: "{y} Q{q} to Q{q2}", fr: "T{q} à T{q2} {y}" },
  "money": { en: "${amount}", fr: "{amount} $" },
  "money.usd": { en: "US${amount}", fr: "{amount} $ US" },
  "wage.range": { en: "${min} to {max}{unit}", fr: "{min} à {max} ${unit}" },
  "wage.single": { en: "${amount}{unit}", fr: "{amount} ${unit}" },
  "wage.unit.HOUR": { en: "/h", fr: "/h" },
  "wage.unit.YEAR": { en: "/yr", fr: "/an" },
  "wage.unit.WEEK": { en: " week", fr: "/semaine" },
  "wage.unit.MONTH": { en: " month", fr: "/mois" },
  "wage.unit.DAY": { en: " day", fr: "/jour" },
  "wage.unit.BIWEEK": { en: " biweek", fr: "/deux semaines" },
  // The posting pages give schema.org's unitText, spelled WEEKLY and BIWEEKLY,
  // and the list-page parser writes SEMIMONTH for semi-monthly pay.
  "wage.unit.WEEKLY": { en: " week", fr: "/semaine" },
  "wage.unit.BIWEEKLY": { en: " biweek", fr: "/deux semaines" },
  "wage.unit.SEMIMONTH": { en: " semi-month", fr: "/demi-mois" },
  "size.mb": { en: "{n} MB", fr: "{n} Mo" },

  // -- statuses, indicators, columns -------------------------------------------
  "status.pending": { en: "Pending", fr: "En attente" },
  "status.approved": { en: "Approved", fr: "Approuvée" },
  "status.refused": { en: "Refused", fr: "Refusée" },
  "status.lapsed": { en: "Lapsed", fr: "Échue" },
  "status.finding": { en: "Finding", fr: "Constat" },
  "status.none": { en: "No current record", fr: "Aucun dossier courant" },
  "ind.newly_incorporated": { en: "Newly incorporated applicant", fr: "Demandeur constitué récemment" },
  "ind.repeat_applicant": { en: "Repeat applicant", fr: "Demandeur récurrent" },
  "ind.wage_at_floor": { en: "Wage at the prevailing-wage floor", fr: "Salaire au plancher du salaire courant" },
  "ind.low_wage_high_unemployment": {
    en: "Low-wage stream in a high-unemployment region",
    fr: "Volet des postes à bas salaire dans une région à chômage élevé",
  },
  "ind.high_volume": { en: "High volume", fr: "Volume élevé" },
  "ind.refused_then_reposted": { en: "Refused then re-posted", fr: "Refus suivi d'une nouvelle offre" },
  "ind_state.triggered": { en: "Triggered", fr: "Déclenché" },
  "ind_state.not_triggered": { en: "Not triggered", fr: "Non déclenché" },
  "ind_state.not_applicable": { en: "Not applicable", fr: "Sans objet" },
  "ind_state.not_evaluated": { en: "Not evaluated", fr: "Non évalué" },
  "col.status": { en: "Status", fr: "Statut" },
  "col.employer": { en: "Employer", fr: "Employeur" },
  "col.job": { en: "Job", fr: "Emploi" },
  "col.job_or_occupation": { en: "Job or occupation", fr: "Emploi ou profession" },
  "col.location": { en: "Location", fr: "Lieu" },
  "col.wage": { en: "Wage", fr: "Salaire" },
  "col.date": { en: "Date", fr: "Date" },
  "col.posted": { en: "Posted", fr: "Publication" },
  "col.positions": { en: "Positions", fr: "Postes" },
  "col.indicators": { en: "Indicators", fr: "Indicateurs" },
  "col.source": { en: "Source", fr: "Source" },
  "col.stream": { en: "Stream", fr: "Volet" },
  "search.stream_legend": { en: "ESDC stream", fr: "Volet (EDSC)" },
  "search.stream_hint": { en: "A field of the quarterly lists only. Postings carry a wage instead.", fr: "Un champ des listes trimestrielles seulement. Les offres indiquent plutôt un salaire." },

  // -- provinces and streams ----------------------------------------------------
  "prov.AB": { en: "Alberta", fr: "Alberta" },
  "prov.BC": { en: "British Columbia", fr: "Colombie-Britannique" },
  "prov.MB": { en: "Manitoba", fr: "Manitoba" },
  "prov.NB": { en: "New Brunswick", fr: "Nouveau-Brunswick" },
  "prov.NL": { en: "Newfoundland and Labrador", fr: "Terre-Neuve-et-Labrador" },
  "prov.NS": { en: "Nova Scotia", fr: "Nouvelle-Écosse" },
  "prov.NT": { en: "Northwest Territories", fr: "Territoires du Nord-Ouest" },
  "prov.NU": { en: "Nunavut", fr: "Nunavut" },
  "prov.ON": { en: "Ontario", fr: "Ontario" },
  "prov.PE": { en: "Prince Edward Island", fr: "Île-du-Prince-Édouard" },
  "prov.QC": { en: "Quebec", fr: "Québec" },
  "prov.SK": { en: "Saskatchewan", fr: "Saskatchewan" },
  "prov.YT": { en: "Yukon", fr: "Yukon" },
  "prov.XX": { en: "Head office outside Canada", fr: "Siège social à l'extérieur du Canada" },
  "stream.high_wage": { en: "High Wage", fr: "Haut salaire" },
  "stream.low_wage": { en: "Low Wage", fr: "Bas salaire" },
  "stream.primary_agriculture": { en: "Primary Agriculture", fr: "Agriculture primaire" },
  "stream.global_talent": { en: "Global Talent Stream", fr: "Volet des talents mondiaux" },
  "stream.permanent_resident": { en: "Permanent Resident Only", fr: "Résidence permanente seulement" },

  // -- error and placeholder pages ---------------------------------------------
  "error.no_data": { en: "Data Not Published Yet", fr: "Données pas encore publiées" },
  "error.no_data_text": { en: "Try again after the next nightly run.", fr: "Réessayez après la prochaine mise à jour de nuit." },
  "error.file": { en: "File Not Published Yet", fr: "Fichier pas encore publié" },
  "error.file_text": { en: "The file {file} is not available yet.", fr: "Le fichier {file} n'est pas encore disponible." },
  "error.file_back": { en: "Back to Data & About", fr: "Retour à Données et à propos" },
  "error.not_found": { en: "Page Not Found", fr: "Page introuvable" },
  "error.not_found_text": { en: "{home} or {search}.", fr: "{home} ou {search}." },
  "error.not_found_home": { en: "Go to the home page", fr: "Aller à la page d'accueil" },
  "error.not_found_search": { en: "search the records", fr: "rechercher dans les dossiers" },
  "error.server": { en: "Something Went Wrong", fr: "Une erreur s'est produite" },
  "error.server_text": { en: "Try again in a moment.", fr: "Réessayez dans un moment." },

  // -- home ----------------------------------------------------------------------
  "home.h1": {
    en: "Who Is Applying to Hire Temporary Foreign Workers, and Who Was Approved",
    fr: "Qui demande à embaucher des travailleurs étrangers temporaires, et qui a été approuvé",
  },
  "home.lead": {
    en: "Public records from Job Bank and Employment and Social Development Canada, merged by employer and refreshed nightly. Every row links to the government record it came from.",
    fr: "Dossiers publics du Guichet-Emplois et d'Emploi et Développement social Canada, regroupés par employeur et mis à jour chaque nuit. Chaque ligne renvoie au dossier gouvernemental d'où elle provient.",
  },
  "home.quick": { en: "Quick views:", fr: "Accès rapide :" },
  "home.quick_pending": { en: "Pending Now", fr: "En attente maintenant" },
  "home.quick_approved": { en: "Approved Last Quarter", fr: "Approuvées au dernier trimestre" },
  "home.quick_refused": { en: "Refused Last Quarter", fr: "Refusées au dernier trimestre" },
  "home.tiles_label": { en: "Headline counts", fr: "Chiffres clés" },
  "home.latest_quarter": { en: "latest quarter", fr: "dernier trimestre" },
  "home.tile_pending": {
    en: 'postings flagged "LMIA requested" on Job Bank, Canada-wide, {date}',
    fr: "offres d'emploi portant la mention « EIMT demandée » au Guichet-Emplois, dans tout le Canada, au {date}",
  },
  "home.tile_approved": { en: "employer records, {positions} positions, {period}", fr: "dossiers d'employeurs, {positions} postes, {period}" },
  "home.tile_approved_published": { en: " (ESDC list published {date})", fr: " (liste d'EDSC publiée le {date})" },
  "home.tile_refused": { en: "employer records, {period} (ESDC negative list)", fr: "dossiers d'employeurs, {period} (liste négative d'EDSC)" },
  "home.tile_findings": {
    en: "employers on IRCC's non-compliance list",
    fr: "employeurs inscrits sur la liste des employeurs non conformes d'IRCC",
  },
  "home.applying": { en: "Applying This Week", fr: "Demandes de la semaine" },
  "home.all_pending": { en: "All Pending ({n})", fr: "Toutes en attente ({n})" },
  "home.recent_approved": { en: "Recently Approved", fr: "Approuvées récemment" },
  "home.all_approved": { en: "All Approved", fr: "Toutes les approbations" },
  "home.recent_approved_note": {
    en: 'Postings whose flag changed to "Approved LMIA" while live on Job Bank.',
    fr: "Offres d'emploi dont la mention est passée à « EIMT approuvée » pendant qu'elles étaient affichées au Guichet-Emplois.",
  },
  "home.largest": { en: "Largest approvals in {period}, by positions.", fr: "Plus grandes approbations, {period}, selon le nombre de postes." },
  "home.no_records_yet": { en: "No records yet.", fr: "Aucun dossier pour l'instant." },
  "home.no_list_rows": { en: "No list rows loaded yet.", fr: "Aucune inscription de liste chargée pour l'instant." },
  "home.by_stream": { en: "Approved Records by Stream, {period}", fr: "Dossiers approuvés par volet, {period}" },
  "home.by_province": { en: "Approved Records by Province, {period}", fr: "Dossiers approuvés par province, {period}" },
  "home.how": { en: "How to Read This Site", fr: "Comment lire ce site" },
  "home.how_pending": {
    en: 'Pending status is Job Bank\'s own "LMIA requested" flag, which the site reads to mean the employer could not find a Canadian worker for the job and applied to hire a temporary foreign worker.',
    fr: "Le statut En attente reprend la mention « EIMT demandée » du Guichet-Emplois. Le site y lit que l'employeur n'a pas trouvé de travailleur canadien pour le poste et a demandé à embaucher un travailleur étranger temporaire.",
  },
  "home.how_indicators": {
    en: 'Indicators are pattern flags with written rules and known false positives. They are not findings. Government findings appear only under "Non-Compliance Findings", from IRCC\'s published list.',
    fr: "Les indicateurs signalent des tendances selon des règles écrites et comportent des faux positifs connus. Ce ne sont pas des constats. Les constats du gouvernement figurent seulement sous « Constats de non-conformité », d'après la liste publiée par IRCC.",
  },
  "home.how_reply": {
    en: "Any employer named here can post a response on its profile. See {methodology} and {corrections}.",
    fr: "Tout employeur nommé ici peut publier une réponse sur son profil. Voir {methodology} et {corrections}.",
  },
  "home.how_reply_corrections": { en: "Corrections and right of reply", fr: "Corrections et droit de réponse" },

  // -- search ---------------------------------------------------------------------
  "search.filters": { en: "Filters", fr: "Filtres" },
  "search.province": { en: "Province", fr: "Province" },
  "search.noc": { en: "Occupation (NOC 2021)", fr: "Profession (CNP 2021)" },
  "search.noc_label": { en: "Occupation", fr: "Profession" },
  "search.noc_placeholder": { en: "Code or title, e.g. 63200 cooks", fr: "Code ou titre, p. ex. 63200 cuisiniers" },
  "search.wage": { en: "Wage (postings only)", fr: "Salaire (offres d'emploi seulement)" },
  "search.min": { en: "Min", fr: "Min." },
  "search.max": { en: "Max", fr: "Max." },
  "search.date_any": { en: "Pending now and {period}", fr: "En attente maintenant et {period}" },
  "search.date_7d": { en: "Posted in the last 7 days", fr: "Publiées dans les 7 derniers jours" },
  "search.date_last_quarter": { en: "Last 92 days and {period}", fr: "92 derniers jours et {period}" },
  "search.date_long": { en: "Since {period} ({n} records, larger download)", fr: "Depuis le {period} ({n} dossiers, téléchargement plus lourd)" },
  "search.any_state": { en: "Any state", fr: "Tous les états" },
  "search.show_results": { en: "Show results", fr: "Voir les résultats" },
  "search.clear": { en: "Clear", fr: "Effacer" },
  "search.records_one": { en: "{n} record", fr: "{n} dossier" },
  "search.records_many": { en: "{n} records", fr: "{n} dossiers" },
  "search.loading": { en: "Loading records", fr: "Chargement des dossiers" },
  "search.note_latest": { en: "pending postings and the {period} lists", fr: "offres en attente et listes du {period}" },
  "search.view": { en: "View", fr: "Affichage" },
  "search.list": { en: "List", fr: "Liste" },
  "search.sort": { en: "Sort", fr: "Trier" },
  "search.sort_newest": { en: "Newest", fr: "Plus récents" },
  "search.sort_name": { en: "Employer A to Z", fr: "Employeur de A à Z" },
  "search.noscript": {
    en: "Filtering needs JavaScript. The same data is in the {downloads}.",
    fr: "Le filtrage nécessite JavaScript. Les mêmes données se trouvent dans les {downloads}.",
  },
  "search.pagination": { en: "Pagination", fr: "Pagination" },
  "search.showing": { en: "Showing {from} to {to} of {total}", fr: "Affichage de {from} à {to} sur {total}" },
  "search.page_of": { en: "Page {page} of {pages}", fr: "Page {page} sur {pages}" },
  "search.prev": { en: "Previous", fr: "Précédente" },
  "search.next": { en: "Next", fr: "Suivante" },
  "search.csv": { en: "Download these results (CSV)", fr: "Télécharger ces résultats (CSV)" },
  "search.footnote": {
    en: 'The quarterly lists carry no wages, so ESDC rows show "n/a". "See posting" means the value is on the Job Bank page and not yet parsed. Records before {period} are in the {downloads}.',
    fr: "Les listes trimestrielles ne donnent aucun salaire : les lignes d'EDSC affichent donc « s.o. ». « Voir l'offre » signifie que la valeur figure sur la page du Guichet-Emplois et n'a pas encore été extraite. Les dossiers antérieurs au {period} se trouvent dans les {downloads}.",
  },
  "search.source_jobbank": { en: "Job Bank {ref}", fr: "Guichet-Emplois {ref}" },
  "search.source_positive": { en: "ESDC positive {period}", fr: "EDSC positive {period}" },
  "search.source_negative": { en: "ESDC negative {period}", fr: "EDSC négative {period}" },
  // search.js only
  "search.no_match": { en: "No records match these filters.", fr: "Aucun dossier ne correspond à ces filtres." },
  "search.so_far": { en: "{count} so far", fr: "{count} jusqu'ici" },
  "search.note_since": { en: "since {period}", fr: "depuis le {period}" },
  "search.gate_long": {
    en: "The long scope holds {rows} records across {files} files, about {size} before compression. Once loaded, it is filtered in the browser with no further downloads.",
    fr: "La période longue compte {rows} dossiers répartis dans {files} fichiers, environ {size} avant compression. Une fois chargée, elle est filtrée dans le navigateur sans autre téléchargement.",
  },
  "search.gate_loading": { en: "Loading {rows} records.", fr: "Chargement de {rows} dossiers." },
  "search.gate_load": { en: "Load {rows} records", fr: "Charger {rows} dossiers" },
  "search.gate_csv": { en: "Downloads Page (CSV)", fr: "Page des téléchargements (CSV)" },
  "search.gate_waiting": { en: "Waiting for your choice", fr: "En attente de votre choix" },
  "search.gate_progress": {
    en: "Loaded {done} of {files} files, {rows} records so far.",
    fr: "{done} fichiers chargés sur {files}, {rows} dossiers jusqu'ici.",
  },

  // -- map ------------------------------------------------------------------------
  "map.period": { en: "Period", fr: "Période" },
  "map.period_long": { en: "Since {period}", fr: "Depuis le {period}" },
  "map.locate": { en: "Use my location", fr: "Utiliser ma position" },
  "map.aria": {
    en: "Map of Canada with employer records grouped by postal area",
    fr: "Carte du Canada avec les dossiers d'employeurs regroupés par secteur postal",
  },
  "map.note": {
    en: "Clusters group records by the first three characters of the postal code and sit at the area centroid, never on a residence. Base map: OpenStreetMap contributors.",
    fr: "Les groupes rassemblent les dossiers selon les trois premiers caractères du code postal et sont placés au centre du secteur, jamais sur une résidence. Fond de carte : contributeurs d'OpenStreetMap.",
  },
  "map.select": { en: "Select an Area", fr: "Choisissez un secteur" },
  "map.select_hint": { en: "Click a cluster to list its employers.", fr: "Cliquez sur un groupe pour afficher ses employeurs." },
  "map.open_list": { en: "Open as a List", fr: "Ouvrir sous forme de liste" },
  // map.js only
  "map.area_title": { en: "Postal Area {fsa} ({prov})", fr: "Secteur postal {fsa} ({prov})" },
  "map.area_summary": {
    en: "{shown} of {total} record(s) in the latest scope shown.",
    fr: "{shown} dossier(s) affiché(s) sur {total} pour la période récente.",
  },
  "map.cluster_title": { en: "{fsa}: {n}", fr: "{fsa} : {n}" },
  "map.cluster_label": { en: "{fsa}, {n} records", fr: "{fsa}, {n} dossiers" },

  // -- employer profile -----------------------------------------------------------
  "employer.title": { en: "Employer", fr: "Employeur" },
  "employer.not_found": { en: "Employer Not Found", fr: "Employeur introuvable" },
  "employer.search_records": { en: "Search the records", fr: "Rechercher dans les dossiers" },
  "employer.breadcrumb": { en: "Breadcrumb", fr: "Fil d'Ariane" },
  "employer.all_provinces": { en: "All provinces", fr: "Toutes les provinces" },
  "employer.no_location": { en: "Location not on record", fr: "Lieu non consigné" },
  "employer.id_line": { en: "{location}. Employer ID {id}", fr: "{location}. Identifiant de l'employeur : {id}" },
  "employer.under_review": { en: "under review, observed on Job Bank {date}", fr: "en cours d'examen, observée au Guichet-Emplois le {date}" },
  "employer.since": { en: "since {date}", fr: "depuis le {date}" },
  "employer.respond": { en: "Submit an Employer Response", fr: "Soumettre une réponse de l'employeur" },
  "employer.correct": { en: "Request a Correction", fr: "Demander une correction" },
  "employer.report": { en: "Report to Service Canada", fr: "Signaler à Service Canada" },
  "employer.registry": { en: "Registry", fr: "Registre" },
  "employer.legal_name": { en: "Legal name", fr: "Dénomination sociale" },
  "employer.number": { en: "Number", fr: "Numéro" },
  "employer.type": { en: "Type", fr: "Type" },
  "employer.registered": { en: "Registered", fr: "Enregistrement" },
  "employer.match": { en: "Match", fr: "Correspondance" },
  "employer.names_seen": { en: "Names seen", fr: "Noms relevés" },
  "employer.active": { en: "Active", fr: "Active" },
  "employer.no_registry": {
    en: "No registry match yet. Federal corporations and Quebec enterprises are matched by name; BC employers are also checked in the BC Registry.",
    fr: "Aucune correspondance au registre pour l'instant. Les sociétés fédérales et les entreprises du Québec sont jumelées par leur nom; les employeurs de la Colombie-Britannique sont aussi vérifiés dans le BC Registry.",
  },
  "employer.struck_off": { en: "Struck off", fr: "Radiée" },
  "employer.view_on": { en: "View on {registry}", fr: "Consulter {registry}" },
  "employer.grade_exact": {
    en: "Exact (normalized name and province or postal code agree)",
    fr: "Exacte (le nom normalisé et la province ou le code postal concordent)",
  },
  "employer.grade_probable": {
    en: "Probable (name only; posting may use a trade name)",
    fr: "Probable (nom seulement; l'offre peut utiliser un nom commercial)",
  },
  "employer.grade_possible": { en: "Possible (name similarity only)", fr: "Possible (similarité de nom seulement)" },
  "employer.location": { en: "Location", fr: "Lieu" },
  "employer.street": { en: "Street", fr: "Adresse" },
  "employer.street_none": { en: "Not in any record", fr: "Absente de tous les dossiers" },
  "employer.city": { en: "City", fr: "Ville" },
  "employer.postal_code": { en: "Postal code", fr: "Code postal" },
  "employer.source_posting": { en: "Job Bank posting {id}", fr: "Offre {id} du Guichet-Emplois" },
  "employer.source_list": { en: "ESDC list {period}", fr: "Liste d'EDSC, {period}" },
  "employer.source_finding": { en: "IRCC finding", fr: "Constat d'IRCC" },
  "employer.map_aria": { en: "Map placeholder at the postal-area centroid", fr: "Emplacement de la carte au centre du secteur postal" },
  "employer.map_text": { en: "Map at postal-area centroid", fr: "Carte au centre du secteur postal" },
  "employer.nearby": { en: "Other Employers Nearby", fr: "Autres employeurs à proximité" },
  "employer.summary": { en: "Summary", fr: "Résumé" },
  "employer.pending_postings": { en: "Pending postings", fr: "Offres en attente" },
  "employer.positions_requested": { en: "Positions requested", fr: "Postes demandés" },
  "employer.approved_lmias": { en: "Approved LMIAs", fr: "EIMT approuvées" },
  "employer.refused_lmias": { en: "Refused LMIAs", fr: "EIMT refusées" },
  "employer.positions_paren_one": { en: "({n} position)", fr: "({n} poste)" },
  "employer.positions_paren_many": { en: "({n} positions)", fr: "({n} postes)" },
  // Many ESDC files, positive and negative, give positions but no LMIA count,
  // so a summed LMIA count covers fewer rows than the records table shows.
  // Each note names its count, since a profile can carry both.
  "employer.lmias_note_one": {
    en: "The approved LMIA count leaves out {n} row from a file that carries no LMIA count.",
    fr: "Le nombre d'EIMT approuvées laisse de côté {n} inscription tirée d'un fichier qui n'indique aucun nombre d'EIMT.",
  },
  "employer.lmias_note_many": {
    en: "The approved LMIA count leaves out {n} rows from files that carry no LMIA count.",
    fr: "Le nombre d'EIMT approuvées laisse de côté {n} inscriptions tirées de fichiers qui n'indiquent aucun nombre d'EIMT.",
  },
  "employer.refused_lmias_note_one": {
    en: "The refused LMIA count leaves out {n} row from a file that carries no LMIA count.",
    fr: "Le nombre d'EIMT refusées laisse de côté {n} inscription tirée d'un fichier qui n'indique aucun nombre d'EIMT.",
  },
  "employer.refused_lmias_note_many": {
    en: "The refused LMIA count leaves out {n} rows from files that carry no LMIA count.",
    fr: "Le nombre d'EIMT refusées laisse de côté {n} inscriptions tirées de fichiers qui n'indiquent aucun nombre d'EIMT.",
  },
  "employer.findings_count": { en: "Non-compliance findings", fr: "Constats de non-conformité" },
  "employer.response": { en: "Employer response", fr: "Réponse de l'employeur" },
  "employer.published_one": { en: "{n} published", fr: "{n} publiée" },
  "employer.published_many": { en: "{n} published", fr: "{n} publiées" },
  "employer.none_received": { en: "None received", fr: "Aucune reçue" },
  "employer.indicators": { en: "Indicators", fr: "Indicateurs" },
  "employer.indicator_link": { en: "Indicator Definitions and Known False Positives", fr: "Définitions des indicateurs et faux positifs connus" },
  "employer.indicator_note": {
    en: "A triggered indicator means the pattern is present. It is not a finding.",
    fr: "Un indicateur déclenché signifie que la tendance est présente. Ce n'est pas un constat.",
  },
  "employer.col_indicator": { en: "Indicator", fr: "Indicateur" },
  "employer.col_state": { en: "State", fr: "État" },
  "employer.col_basis": { en: "Basis", fr: "Fondement" },
  "employer.not_computed": { en: "Not computed yet.", fr: "Pas encore calculé." },
  "employer.findings": { en: "Non-Compliance Findings (IRCC)", fr: "Constats de non-conformité (IRCC)" },
  "employer.col_decision": { en: "Decision", fr: "Décision" },
  "employer.col_operating_name": { en: "Operating name", fr: "Nom commercial" },
  "employer.col_address": { en: "Address", fr: "Adresse" },
  "employer.col_reasons": { en: "Reasons", fr: "Motifs" },
  "employer.col_penalty": { en: "Penalty", fr: "Sanction" },
  "employer.timeline": { en: "Timeline", fr: "Chronologie" },
  "employer.ev_registered": { en: "{name} registered ({registry})", fr: "Enregistrement de {name} ({registry})" },
  "employer.ev_published": {
    en: 'Job Bank posting {id} published with the "LMIA requested" flag: {title}{wage}',
    fr: "Offre {id} publiée au Guichet-Emplois avec la mention « EIMT demandée » : {title}{wage}",
  },
  "employer.untitled": { en: "untitled", fr: "sans titre" },
  "employer.ev_first_seen": {
    en: "Posting {id} first observed by the nightly check",
    fr: "Offre {id} observée pour la première fois par la vérification de nuit",
  },
  "employer.ev_approved": { en: 'Posting {id} seen with the "Approved LMIA" flag', fr: "Offre {id} vue avec la mention « EIMT approuvée »" },
  "employer.ev_closes": { en: "Posting {id} closes (employer-set expiry)", fr: "Fermeture de l'offre {id} (échéance fixée par l'employeur)" },
  "employer.ev_positive": {
    en: "Positive LMIA list, {period}: {noc}, {positions} position(s){published}",
    fr: "Liste des EIMT positives, {period} : {noc}, {positions} poste(s){published}",
  },
  "employer.ev_negative": {
    en: "Negative LMIA list, {period}: {noc}, {positions} position(s){published}",
    fr: "Liste des EIMT négatives, {period} : {noc}, {positions} poste(s){published}",
  },
  "employer.ev_list_published": { en: " (list published {date})", fr: " (liste publiée le {date})" },
  "employer.ev_finding": { en: "IRCC finding: {penalty} {status}", fr: "Constat d'IRCC : {penalty} {status}" },
  "employer.pending_label": { en: "pending", fr: "en attente" },
  "employer.ev_decision": {
    en: 'Decision: appears on Job Bank as "Approved LMIA" if decided while the posting is live, and in the ESDC quarterly list three to four months after the quarter closes',
    fr: "Décision : paraît au Guichet-Emplois comme « EIMT approuvée » si elle est rendue pendant que l'offre est affichée, et dans la liste trimestrielle d'EDSC trois à quatre mois après la fin du trimestre",
  },
  "employer.no_dated": { en: "No dated records.", fr: "Aucun dossier daté." },
  "employer.records": { en: "Records", fr: "Dossiers" },
  "employer.records_newest": {
    en: "The newest {shown} of {total} list rows are shown. All are in the {json}.",
    fr: "Les {shown} inscriptions les plus récentes sur {total} sont affichées. Toutes figurent dans le {json}.",
  },
  "employer.profile_json": { en: "profile JSON", fr: "JSON du profil" },
  "employer.col_record": { en: "Record", fr: "Dossier" },
  "employer.col_occupation": { en: "Occupation", fr: "Profession" },
  "employer.col_pulled": { en: "Pulled", fr: "Relevé" },
  "employer.posting": { en: "posting", fr: "offre" },
  "employer.open_until": { en: ", open until {date}", fr: ", ouverte jusqu'au {date}" },
  "employer.noc": { en: "NOC {code}", fr: "CNP {code}" },
  "employer.esdc_record": { en: "{stream} stream, {lmias} LMIA(s){place}", fr: "Volet {stream}, {lmias} EIMT{place}" },
  "employer.show_all": { en: "Show all {n} list rows", fr: "Afficher les {n} inscriptions" },
  "employer.response_h": { en: "Employer Response", fr: "Réponse de l'employeur" },
  "employer.received": { en: "Received {date}{contact}", fr: "Reçue le {date}{contact}" },
  "employer.no_response": {
    en: "No response has been submitted. The employer can post a statement that appears here unedited, with the date received.",
    fr: "Aucune réponse n'a été soumise. L'employeur peut publier une déclaration qui paraîtra ici sans modification, avec la date de réception.",
  },
  "employer.submit_response": { en: "Submit a Response", fr: "Soumettre une réponse" },
  "employer.corrections_log": { en: "Corrections Log", fr: "Journal des corrections" },
  "employer.resolution": { en: " Resolution ({date}): {text}", fr: " Résolution ({date}) : {text}" },
  "employer.no_corrections": {
    en: "No corrections on this profile. Changes are listed here with the date and the reason.",
    fr: "Aucune correction sur ce profil. Les modifications sont inscrites ici avec la date et le motif.",
  },
  "employer.info": { en: "If You Have Information About This Employer", fr: "Si vous avez des renseignements sur cet employeur" },
  "employer.info_report": {
    en: "Service Canada investigates misuse of the Temporary Foreign Worker Program. Call 1-866-602-9448 (24 hours a day, 7 days a week) or use the {form}. Reports are handled under Canada's privacy laws.",
    fr: "Service Canada enquête sur l'utilisation abusive du Programme des travailleurs étrangers temporaires. Composez le 1-866-602-9448 (24 heures sur 24, 7 jours sur 7) ou utilisez le {form}. Les signalements sont traités conformément aux lois canadiennes sur la protection des renseignements personnels.",
  },
  "employer.info_form": { en: "online report form", fr: "formulaire de signalement en ligne" },
  "employer.info_rights": {
    en: "Temporary foreign workers have the same rights as Canadian workers. The report page also lists help lines and the open work permit for vulnerable workers.",
    fr: "Les travailleurs étrangers temporaires ont les mêmes droits que les travailleurs canadiens. La page de signalement indique aussi les lignes d'aide et le permis de travail ouvert pour les travailleurs vulnérables.",
  },
  "entity.BC": { en: "BC company", fr: "Société de la Colombie-Britannique" },
  "entity.SP": { en: "Sole proprietorship", fr: "Entreprise individuelle" },
  "entity.GP": { en: "General partnership", fr: "Société en nom collectif" },
  "entity.LP": { en: "Limited partnership", fr: "Société en commandite" },
  "entity.ULC": { en: "Unlimited liability company", fr: "Société à responsabilité illimitée" },
  "entity.S": { en: "Society", fr: "Société sans but lucratif (society)" },
  "entity.A": { en: "Extraprovincial company", fr: "Société extraprovinciale" },
  "entity.C": { en: "Continuation", fr: "Prorogation" },
  "entity.CBCA": {
    en: "Federal corporation (Canada Business Corporations Act)",
    fr: "Société fédérale (Loi canadienne sur les sociétés par actions)",
  },
  "entity.CIE": { en: "Business corporation (Quebec)", fr: "Société par actions (Québec)" },
  "entity.SENC": { en: "General partnership (Quebec)", fr: "Société en nom collectif (Québec)" },
  "entity.SEC": { en: "Limited partnership (Quebec)", fr: "Société en commandite (Québec)" },
  "entity.APE": { en: "Non-profit legal person (Quebec)", fr: "Personne morale sans but lucratif (Québec)" },
  "entity.COP": { en: "Co-operative (Quebec)", fr: "Coopérative (Québec)" },
  "registry.bc_orgbook": { en: "BC Registry (OrgBook)", fr: "BC Registry (OrgBook)" },
  "registry.corporations_canada": { en: "Corporations Canada", fr: "Corporations Canada" },
  "registry.quebec_req": { en: "Quebec enterprise register", fr: "Registre des entreprises du Québec" },

  // -- forms ------------------------------------------------------------------------
  "form.respond_intro": {
    en: "For {employer}. Statements are posted unedited on the profile with the date received, once the sender is verified against the contact details on the Job Bank posting or registry record.",
    fr: "Pour {employer}. Les déclarations sont publiées sans modification sur le profil, avec la date de réception, une fois l'expéditeur vérifié à l'aide des coordonnées de l'offre du Guichet-Emplois ou du dossier du registre.",
  },
  "form.name": { en: "Your name and role", fr: "Votre nom et votre rôle" },
  "form.work_email": { en: "Work email (used only for verification)", fr: "Courriel professionnel (utilisé seulement pour la vérification)" },
  "form.statement": { en: "Statement", fr: "Déclaration" },
  "form.honeypot": { en: "Leave this field empty", fr: "Laissez ce champ vide" },
  "form.submit_statement": { en: "Submit statement", fr: "Soumettre la déclaration" },
  "form.err_name": { en: "Enter your name and role.", fr: "Inscrivez votre nom et votre rôle." },
  "form.err_email": { en: "Enter a valid work email address.", fr: "Inscrivez une adresse de courriel professionnelle valide." },
  "form.err_statement": { en: "The statement needs at least 20 characters.", fr: "La déclaration doit compter au moins 20 caractères." },
  "form.thanks_statement": {
    en: "Your statement was received and will appear on the profile once the sender is verified.",
    fr: "Votre déclaration a été reçue et paraîtra sur le profil une fois l'expéditeur vérifié.",
  },
  "form.correct_intro": {
    en: "Anyone can report a wrong match, a stale record or a misfiring indicator. Changes appear in the profile's corrections log after review.",
    fr: "Toute personne peut signaler une mauvaise correspondance, un dossier périmé ou un indicateur erroné. Les modifications paraissent dans le journal des corrections du profil après examen.",
  },
  "form.record_ref": { en: "Profile or record", fr: "Profil ou dossier" },
  "form.record_placeholder": { en: "emp-xxxxxxxxxx or Job Bank 50456228", fr: "emp-xxxxxxxxxx ou Guichet-Emplois 50456228" },
  "form.what_wrong": { en: "What is wrong", fr: "Ce qui est inexact" },
  "form.reply_email": { en: "Email for a reply (optional)", fr: "Courriel pour une réponse (facultatif)" },
  "form.send_correction": { en: "Send correction", fr: "Envoyer la correction" },
  "form.err_record": { en: "Name the profile or record.", fr: "Indiquez le profil ou le dossier." },
  "form.err_request": { en: "Describe what is wrong in at least 10 characters.", fr: "Décrivez ce qui est inexact en au moins 10 caractères." },
  "form.err_reply_email": { en: "The email address does not look valid.", fr: "L'adresse de courriel ne semble pas valide." },
  "form.thanks_correction": { en: "Your correction request was received.", fr: "Votre demande de correction a été reçue." },
  "form.thanks": { en: "Thank You", fr: "Merci" },
  "form.rejected": { en: "Rejected", fr: "Refusé" },

  // -- methodology ------------------------------------------------------------------
  "methodology.toc_sources": { en: "Sources", fr: "Sources" },
  "methodology.toc_status": { en: "Status Lifecycle", fr: "Cycle de vie des statuts" },
  "methodology.toc_matching": { en: "Matching Employers", fr: "Jumelage des employeurs" },
  "methodology.toc_exclusions": { en: "Exclusions", fr: "Exclusions" },
  "methodology.toc_limits": { en: "Limits", fr: "Limites" },
  "methodology.toc_versions": { en: "Versions", fr: "Versions" },
  "methodology.lead": {
    en: "Everything here is reproducible from the downloads on the Data page.",
    fr: "Tout ce qui figure ici peut être reproduit à partir des téléchargements de la page Données.",
  },
  "methodology.col_fields": { en: "Fields", fr: "Champs" },
  "methodology.col_cadence": { en: "Cadence", fr: "Fréquence" },
  "methodology.col_lag": { en: "Lag", fr: "Délai" },
  "methodology.sources.jobbank_requested.source": {
    en: 'Job Bank postings with the "LMIA requested" flag (search facet 101010)',
    fr: "Offres du Guichet-Emplois portant la mention « EIMT demandée » (filtre de recherche 101010)",
  },
  "methodology.sources.jobbank_requested.fields": {
    en: "Employer, job title, city, postal code, street when entered, wage, posting and expiry dates, flag text",
    fr: "Employeur, titre du poste, ville, code postal, rue si elle est inscrite, salaire, dates de publication et d'expiration, texte de la mention",
  },
  "methodology.sources.jobbank_requested.cadence": {
    en: "Nightly check, every observation stored",
    fr: "Vérification chaque nuit, chaque observation conservée",
  },
  "methodology.sources.jobbank_requested.lag": {
    en: "None. The flag disappears once a decision lands, so the nightly record is the only durable record of a pending application.",
    fr: "Aucun. La mention disparaît dès qu'une décision est rendue : le relevé de nuit est donc la seule trace durable d'une demande en attente.",
  },
  "methodology.sources.jobbank_approved.source": {
    en: 'Job Bank postings with the "Approved LMIA" flag (facet 101020)',
    fr: "Offres du Guichet-Emplois portant la mention « EIMT approuvée » (filtre 101020)",
  },
  "methodology.sources.same_fields": { en: "Same fields", fr: "Mêmes champs" },
  "methodology.sources.nightly": { en: "Nightly", fr: "Chaque nuit" },
  "methodology.sources.jobbank_approved.lag": {
    en: "None, but only for postings still live when the decision arrived",
    fr: "Aucun, mais seulement pour les offres encore affichées au moment de la décision",
  },
  "methodology.sources.esdc_positive.source": {
    en: "ESDC positive LMIA employers list (open.canada.ca)",
    fr: "Liste des employeurs ayant reçu une EIMT positive, EDSC (open.canada.ca)",
  },
  "methodology.sources.esdc_positive.fields": {
    en: "Province, stream, employer, city and postal code, NOC 2021 occupation, incorporation status, approved LMIAs, approved positions",
    fr: "Province, volet, employeur, ville et code postal, profession selon la CNP 2021, statut de constitution, EIMT approuvées, postes approuvés",
  },
  "methodology.sources.esdc_positive.cadence": { en: "Quarterly spreadsheet", fr: "Tableur trimestriel" },
  "methodology.sources.esdc_positive.lag": {
    en: "Three to four months. The Jan to Mar 2026 file was published 2026-07-21.",
    fr: "Trois à quatre mois. Le fichier de janvier à mars 2026 a été publié le 2026-07-21.",
  },
  "methodology.sources.esdc_negative.source": {
    en: "ESDC negative LMIA employers list",
    fr: "Liste des employeurs ayant reçu une EIMT négative, EDSC",
  },
  "methodology.sources.esdc_negative.fields": {
    en: "Same fields, with requested LMIAs and requested positions",
    fr: "Mêmes champs, avec les EIMT demandées et les postes demandés",
  },
  "methodology.sources.esdc_negative.cadence": { en: "Quarterly", fr: "Trimestrielle" },
  "methodology.sources.esdc_negative.lag": { en: "Same", fr: "Même délai" },
  "methodology.sources.ircc.source": { en: "IRCC employers found non-compliant", fr: "Employeurs jugés non conformes, IRCC" },
  "methodology.sources.ircc.fields": {
    en: "Operating and legal name, address, reasons, date of final decision, penalty, status",
    fr: "Nom commercial et dénomination sociale, adresse, motifs, date de la décision finale, sanction, statut",
  },
  "methodology.sources.ircc.cadence": { en: "Updated as decisions are published", fr: "Mise à jour à la publication des décisions" },
  "methodology.sources.ircc.lag": { en: "Varies", fr: "Variable" },
  "methodology.sources.registry.source": {
    en: "BC Registry via OrgBook; Corporations Canada's open-data extract of federal corporations; the Registraire des entreprises du Québec's open-data register (CC BY-NC-SA 4.0)",
    fr: "BC Registry au moyen d'OrgBook; extrait des données ouvertes de Corporations Canada sur les sociétés fédérales; registre des entreprises en données ouvertes du Registraire des entreprises du Québec (CC BY-NC-SA 4.0)",
  },
  "methodology.sources.registry.fields": {
    en: "Legal name, registration number (Quebec enterprise number in Quebec), entity type, status, registration date",
    fr: "Dénomination sociale, numéro d'enregistrement (numéro d'entreprise du Québec au Québec), type d'entité, statut, date d'enregistrement",
  },
  "methodology.sources.registry.cadence": {
    en: "BC employers nightly, those with current records first, each looked up again after 180 days; the federal extract weekly; the Quebec register weekly",
    fr: "Employeurs de la Colombie-Britannique chaque nuit, ceux qui ont des dossiers récents d'abord, chacun vérifié de nouveau après 180 jours; extrait fédéral chaque semaine; registre du Québec chaque semaine",
  },
  "methodology.sources.none": { en: "None", fr: "Aucun" },
  "methodology.sources.wages.source": {
    en: "Job Bank wages by occupation and economic region (ESDC, open.canada.ca)",
    fr: "Salaires par profession et par région économique du Guichet-Emplois (EDSC, open.canada.ca)",
  },
  "methodology.sources.wages.fields": {
    en: "Low, median and high wage for each NOC 2021 occupation, by economic region, province and Canada. The median is the LMIA wage floor.",
    fr: "Salaire bas, médian et élevé de chaque profession de la CNP 2021, par région économique, par province et pour le Canada. La médiane est le plancher salarial de l'EIMT.",
  },
  "methodology.sources.wages.cadence": {
    en: "Yearly (the 2025 table is dated 2025-11-19); checked monthly",
    fr: "Annuelle (la table de 2025 est datée du 2025-11-19); vérifiée chaque mois",
  },
  "methodology.sources.wages.lag": { en: "Used only by the wage indicator", fr: "Utilisé seulement par l'indicateur salarial" },
  "methodology.sources.lfs.source": {
    en: "Statistics Canada Labour Force Survey, table 14-10-0459-01",
    fr: "Enquête sur la population active de Statistique Canada, tableau 14-10-0459-01",
  },
  "methodology.sources.lfs.fields": {
    en: "Unemployment rate by census metropolitan area, three-month moving average, unadjusted for seasonality (the figures ESDC's refusal table shows)",
    fr: "Taux de chômage par région métropolitaine de recensement, moyenne mobile de trois mois, données non désaisonnalisées (les chiffres du tableau des refus d'EDSC)",
  },
  "methodology.sources.lfs.cadence": { en: "Monthly; checked monthly", fr: "Mensuelle; vérifiée chaque mois" },
  "methodology.sources.lfs.lag": {
    en: "Used only by the low-wage stream indicator",
    fr: "Utilisé seulement par l'indicateur du volet des postes à bas salaire",
  },
  "methodology.sources.boundaries.source": {
    en: "Statistics Canada 2021 Census boundary files: economic regions, census metropolitan areas, forward sortation areas",
    fr: "Fichiers des limites du Recensement de 2021 de Statistique Canada : régions économiques, régions métropolitaines de recensement, régions de tri d'acheminement",
  },
  "methodology.sources.boundaries.fields": {
    en: "Place each postal area in an economic region and, where it falls in one, a census metropolitan area. An area that straddles a boundary goes wholly to one side.",
    fr: "Situent chaque secteur postal dans une région économique et, s'il y a lieu, dans une région métropolitaine de recensement. Un secteur à cheval sur une limite est rattaché en entier à un seul côté.",
  },
  "methodology.sources.boundaries.cadence": {
    en: "Loaded once; boundaries are fixed for a census",
    fr: "Chargés une seule fois; les limites sont fixes pour un recensement",
  },
  "methodology.sources.program.source": {
    en: "ESDC program pages on canada.ca: LMIA processing times, refusal to process (low-wage positions by census metropolitan area), hourly wage thresholds",
    fr: "Pages de programme d'EDSC sur canada.ca : délais de traitement des EIMT, refus de traitement (postes à bas salaire par région métropolitaine de recensement), seuils salariaux horaires",
  },
  "methodology.sources.program.fields": {
    en: "Average business days by stream for a month; unemployment rate by census metropolitan area with the dates each list is in force; hourly threshold by province and territory with its effective date",
    fr: "Jours ouvrables moyens par volet pour un mois; taux de chômage par région métropolitaine de recensement avec les dates d'application de chaque liste; seuil horaire par province et territoire avec sa date d'entrée en vigueur",
  },
  "methodology.sources.program.cadence": {
    en: "Monthly, quarterly and yearly as ESDC updates them; read nightly",
    fr: "Mensuelle, trimestrielle et annuelle selon les mises à jour d'EDSC; relevées chaque nuit",
  },
  "methodology.sources.program.lag": {
    en: "Processing times describe the month before; the lists are used by the low-wage stream indicator",
    fr: "Les délais de traitement portent sur le mois précédent; les listes servent à l'indicateur du volet des postes à bas salaire",
  },
  "methodology.status_note": {
    en: "Each posting or list row is one record. An employer's status is the most recent record's status.",
    fr: "Chaque offre ou inscription de liste constitue un dossier. Le statut d'un employeur est celui de son dossier le plus récent.",
  },
  "methodology.col_assigned": { en: "Assigned when", fr: "Attribué quand" },
  "methodology.col_ends": { en: "Ends when", fr: "Prend fin quand" },
  "methodology.status.pending.assigned": {
    en: 'A Job Bank posting carries the "LMIA requested" flag in the latest check',
    fr: "Une offre du Guichet-Emplois porte la mention « EIMT demandée » lors de la dernière vérification",
  },
  "methodology.status.pending.ends": {
    en: "The flag changes to approved, the employer appears in a quarterly list, or the posting closes with no decision seen",
    fr: "La mention passe à approuvée, l'employeur paraît dans une liste trimestrielle, ou l'offre prend fin sans décision observée",
  },
  "methodology.status.approved.assigned": {
    en: 'The Job Bank flag reads "Approved LMIA", or the employer, city and occupation appear in a positive quarterly list',
    fr: "La mention du Guichet-Emplois indique « EIMT approuvée », ou l'employeur, la ville et la profession paraissent dans une liste trimestrielle positive",
  },
  "methodology.status.approved.ends": {
    en: "Never. Approved records stay on the profile with their quarter.",
    fr: "Jamais. Les dossiers approuvés restent sur le profil avec leur trimestre.",
  },
  "methodology.status.refused.assigned": {
    en: "The employer, city and occupation appear in a negative quarterly list",
    fr: "L'employeur, la ville et la profession paraissent dans une liste trimestrielle négative",
  },
  "methodology.status.never": { en: "Never", fr: "Jamais" },
  "methodology.status.lapsed.assigned": {
    en: "A pending posting closed and two full quarterly lists have been published since, with no matching row in either",
    fr: "Une offre en attente a pris fin et deux listes trimestrielles complètes ont été publiées depuis, sans ligne correspondante dans l'une ou l'autre",
  },
  "methodology.status.lapsed.ends": { en: "A later list matches it", fr: "Une liste ultérieure y correspond" },
  "methodology.status.finding.assigned": {
    en: "The employer appears on IRCC's non-compliant list",
    fr: "L'employeur figure sur la liste des employeurs non conformes d'IRCC",
  },
  "methodology.status.finding.ends": {
    en: "Never. Shown apart from the other statuses and from the indicators because it is a government decision.",
    fr: "Jamais. Affiché à part des autres statuts et des indicateurs, car il s'agit d'une décision du gouvernement.",
  },
  "methodology.indicators_note": {
    en: "Each indicator is a mechanical rule over the records. A triggered indicator means the pattern is present. It does not mean the employer did anything wrong.",
    fr: "Chaque indicateur est une règle mécanique appliquée aux dossiers. Un indicateur déclenché signifie que la tendance est présente. Il ne signifie pas que l'employeur a commis une faute.",
  },
  "methodology.col_rule": { en: "Rule", fr: "Règle" },
  "methodology.col_data": { en: "Data", fr: "Données" },
  "methodology.col_false_positives": { en: "Known false positives", fr: "Faux positifs connus" },
  "methodology.ind.newly_incorporated.rule": {
    en: "Registration date of the matched entity is less than 12 months before the posting date",
    fr: "La date d'enregistrement de l'entité jumelée précède de moins de 12 mois la date de l'offre",
  },
  "methodology.ind.newly_incorporated.data": { en: "Registry, Job Bank", fr: "Registre, Guichet-Emplois" },
  "methodology.ind.newly_incorporated.fp": {
    en: "An existing business that changed form (sole proprietorship to corporation), a franchise opening, a business that moved provinces",
    fr: "Une entreprise existante qui a changé de forme (d'entreprise individuelle à société), l'ouverture d'une franchise, une entreprise qui a changé de province",
  },
  "methodology.ind.repeat_applicant.rule": {
    en: "Same employer and occupation in three or more consecutive quarterly positive lists",
    fr: "Même employeur et même profession dans au moins trois listes positives trimestrielles consécutives",
  },
  "methodology.ind.positive_lists": { en: "ESDC positive lists", fr: "Listes positives d'EDSC" },
  "methodology.ind.repeat_applicant.fp": {
    en: "Seasonal agriculture under the Seasonal Agricultural Worker Program renews yearly by design; hospitals and long-term care recruit continuously",
    fr: "L'agriculture saisonnière relevant du Programme des travailleurs agricoles saisonniers se renouvelle chaque année par conception; les hôpitaux et les soins de longue durée recrutent sans arrêt",
  },
  "methodology.ind.wage_at_floor.rule": {
    en: "Posted minimum wage is within 1 percent of the Job Bank median for the posting's occupation and economic region, in the wage table in force on the posting date; where Job Bank publishes no regional median, the provincial and then the national median, as ESDC tells employers",
    fr: "Le salaire minimum affiché se situe à 1 % ou moins de la médiane du Guichet-Emplois pour la profession et la région économique de l'offre, dans la table des salaires en vigueur à la date de publication; à défaut de médiane régionale, la médiane provinciale, puis nationale, comme EDSC l'indique aux employeurs",
  },
  "methodology.ind.wage_at_floor.data": {
    en: "Job Bank posting, Job Bank wage table, 2021 Census boundaries",
    fr: "Offre du Guichet-Emplois, table des salaires du Guichet-Emplois, limites du Recensement de 2021",
  },
  "methodology.ind.wage_at_floor.fp": {
    en: "Occupations with a narrow wage distribution; a posting whose range starts at the floor but pays above it; a postal area that straddles two economic regions and is placed in the other one",
    fr: "Professions dont la répartition des salaires est étroite; une offre dont la fourchette commence au plancher mais qui paie davantage; un secteur postal à cheval sur deux régions économiques et rattaché à l'autre",
  },
  "methodology.ind.low_wage_high_unemployment.rule": {
    en: "A positive-list row from 2025 Q1 on is in the Low Wage stream, and its census metropolitan area's unemployment rate was 6 percent or higher in both three-month periods that could have applied: the one in force when the decision quarter began and the one before it. For a quarter whose two lists this site has read from ESDC's refusal-to-process page (see Program conditions), the rates are the ones ESDC published; for earlier quarters they are reconstructed from Statistics Canada's Labour Force Survey, the series ESDC draws them from. Each profile's basis sentence names which was used. Since 2024-09-26 ESDC refuses to process low-wage applications in such areas outside exempt positions",
    fr: "Une inscription sur la liste positive depuis le T1 2025 relève du volet des postes à bas salaire, et le taux de chômage de sa région métropolitaine de recensement était d'au moins 6 % pendant les deux périodes de trois mois qui pouvaient s'appliquer : celle en vigueur au début du trimestre de la décision et la précédente. Pour un trimestre dont ce site a relevé les deux listes sur la page des refus de traitement d'EDSC (voir Conditions du programme), les taux sont ceux qu'EDSC a publiés; pour les trimestres antérieurs, ils sont reconstitués à partir de l'Enquête sur la population active de Statistique Canada, la série dont EDSC les tire. La phrase de fondement de chaque profil indique laquelle a servi. Depuis le 2024-09-26, EDSC refuse de traiter les demandes à bas salaire dans ces régions, sauf pour les postes exemptés",
  },
  "methodology.ind.low_wage_high_unemployment.data": {
    en: "ESDC positive lists, ESDC's refusal-to-process lists (canada.ca), Statistics Canada Labour Force Survey, 2021 Census boundaries",
    fr: "Listes positives d'EDSC, listes des refus de traitement d'EDSC (canada.ca), Enquête sur la population active de Statistique Canada, limites du Recensement de 2021",
  },
  "methodology.ind.low_wage_high_unemployment.fp": {
    en: "Exempt positions: primary agriculture, construction, food manufacturing including fish processing, hospitals, nursing and residential care, in-home caregivers in a private household, permanent residence only, and stays of 120 days or less; an application submitted before 2024-09-26 and decided later; a postal area that straddles a metropolitan boundary",
    fr: "Postes exemptés : agriculture primaire, construction, fabrication d'aliments, y compris la transformation du poisson, hôpitaux, soins infirmiers et soins en établissement résidentiel, aides familiaux dans un ménage privé, résidence permanente seulement et séjours de 120 jours ou moins; une demande présentée avant le 2024-09-26 et tranchée plus tard; un secteur postal à cheval sur la limite d'une région métropolitaine",
  },
  "methodology.ind.high_volume.rule": {
    en: "Approved positions in one quarter of 50 or more, or ten times the employer's own median quarter",
    fr: "Au moins 50 postes approuvés en un trimestre, ou dix fois le trimestre médian de l'employeur",
  },
  "methodology.ind.high_volume.fp": {
    en: "Large farms, greenhouses and packers; health authorities",
    fr: "Grandes exploitations agricoles, serres et emballeurs; autorités sanitaires",
  },
  "methodology.ind.refused_then_reposted.rule": {
    en: "A negative-list row followed by a new pending posting within 90 days of the list's publication",
    fr: "Une inscription sur la liste négative suivie d'une nouvelle offre en attente dans les 90 jours suivant la publication de la liste",
  },
  "methodology.ind.refused_then_reposted.data": { en: "ESDC negative list, Job Bank", fr: "Liste négative d'EDSC, Guichet-Emplois" },
  "methodology.ind.refused_then_reposted.fp": {
    en: "A refusal for a paperwork defect that was corrected and resubmitted",
    fr: "Un refus pour un vice de forme qui a été corrigé, suivi d'une nouvelle demande",
  },
  "methodology.recompute": { en: "A change to any rule recomputes every profile.", fr: "Toute modification d'une règle entraîne le recalcul de tous les profils." },
  "methodology.matching": { en: "Matching Employers Across Sources", fr: "Jumelage des employeurs entre les sources" },
  "methodology.matching_text": {
    en: 'An employer is its legal name and province. When a name carries a trade name after "dba", "o/a", "operating as", "faisant affaire sous" or a similar marker, the part before the marker is the legal name and the trade name is listed among the names seen. Names are normalized before comparison: case and accents folded; dots in abbreviations (B.C.) and apostrophes removed; other punctuation, "&", "and" and "et" dropped; spaced initials joined (J M Farms reads as JM Farms); the province in a numbered company name spelled one way (0704250 B.C. Ltd. and 0704250 BC Ltd. agree); legal suffixes stripped (Ltd., Inc., Corp., Ltée, S.E.N.C., Limited Partnership). Records whose normalized legal names and provinces agree share one profile.',
    fr: "Un employeur correspond à sa dénomination sociale et à sa province. Lorsqu'un nom porte un nom commercial après « dba », « o/a », « operating as », « faisant affaire sous » ou une mention semblable, la partie qui précède la mention est la dénomination sociale et le nom commercial figure parmi les noms relevés. Les noms sont normalisés avant la comparaison : casse et accents uniformisés; points des abréviations (B.C.) et apostrophes retirés; autre ponctuation, « & », « and » et « et » supprimés; initiales espacées réunies (J M Farms se lit JM Farms); province d'une société à numéro écrite d'une seule façon (0704250 B.C. Ltd. et 0704250 BC Ltd. concordent); suffixes juridiques supprimés (Ltd., Inc., Corp., Ltée, S.E.N.C., Limited Partnership). Les dossiers dont la dénomination normalisée et la province concordent partagent un profil.",
  },
  "methodology.col_grade": { en: "Grade", fr: "Niveau" },
  "methodology.col_condition": { en: "Condition", fr: "Critère" },
  "methodology.col_shown_as": { en: "Shown as", fr: "Présentation" },
  "methodology.grade.exact": { en: "Exact", fr: "Exacte" },
  "methodology.grade.exact.condition": {
    en: "The normalized name equals the registered legal name; for the federal and Quebec registers the province or postal code agrees too",
    fr: "Le nom normalisé est égal à la dénomination enregistrée; pour les registres fédéral et québécois, la province ou le code postal concorde aussi",
  },
  "methodology.grade.exact.shown": { en: 'Registry card marked "Exact"', fr: "Fiche du registre marquée « Exacte »" },
  "methodology.grade.probable": { en: "Probable", fr: "Probable" },
  "methodology.grade.probable.condition": {
    en: "The names agree but the province and postal code do not, the name is one the enterprise operates under (Quebec), or one name contains the other (BC Registry)",
    fr: "Les noms concordent mais ni la province ni le code postal, le nom est un nom sous lequel l'entreprise exerce (Québec), ou l'un des noms contient l'autre (BC Registry)",
  },
  "methodology.grade.probable.shown": {
    en: 'Registry card marked "Probable", with the names seen listed',
    fr: "Fiche du registre marquée « Probable », avec la liste des noms relevés",
  },
  "methodology.grade.possible": { en: "Possible", fr: "Possible" },
  "methodology.grade.possible.condition": {
    en: "BC Registry only: the closest search result shares no normalized name with the employer",
    fr: "BC Registry seulement : le résultat de recherche le plus proche ne partage aucun nom normalisé avec l'employeur",
  },
  "methodology.grade.possible.shown": {
    en: 'Registry card marked "Possible"; treat it as a lead, not a match',
    fr: "Fiche du registre marquée « Possible »; c'est une piste, pas une correspondance",
  },
  "methodology.grade.unmatched": { en: "Unmatched", fr: "Non jumelé" },
  "methodology.grade.unmatched.condition": { en: "No result in any register checked", fr: "Aucun résultat dans les registres consultés" },
  "methodology.grade.unmatched.shown": { en: "Profile with no registry details", fr: "Profil sans renseignements de registre" },
  "methodology.registry_coverage": {
    en: "Registry coverage: every employer is compared with the federal corporations extract; BC employers are also looked up in the BC Registry through OrgBook, and Quebec employers in the Quebec enterprise register. Ontario, Alberta, Saskatchewan, Manitoba, New Brunswick, Nova Scotia, Prince Edward Island and Newfoundland and Labrador publish no free bulk file or open interface for their corporate registers: their searches go one name at a time, several charge a fee per search or need an account, and some terms forbid automated searching. A company incorporated in one of those provinces shows registry details only when it is also a federal corporation.",
    fr: "Couverture des registres : chaque employeur est comparé à l'extrait des sociétés fédérales; les employeurs de la Colombie-Britannique sont aussi cherchés dans le BC Registry au moyen d'OrgBook, et ceux du Québec dans le registre des entreprises du Québec. L'Ontario, l'Alberta, la Saskatchewan, le Manitoba, le Nouveau-Brunswick, la Nouvelle-Écosse, l'Île-du-Prince-Édouard et Terre-Neuve-et-Labrador ne publient ni fichier complet gratuit ni interface ouverte pour leur registre des sociétés : on y cherche un nom à la fois, plusieurs facturent chaque recherche ou exigent un compte, et certaines conditions interdisent la recherche automatisée. Une société constituée dans l'une de ces provinces n'affiche des renseignements de registre que si elle est aussi une société fédérale.",
  },
  "methodology.exclusions_households": {
    en: "Private households and individuals are not published. A private home is not a business, and the person who hires help for it is not a public employer. Caregiver and home-support postings where the employer is a person are dropped before anything is stored. ESDC's lists say they leave out personal names, yet some households appear in them: a list row is left out when the occupation is home child care provider or home support worker (NOC 4411, 4412, 44100 or 44101) and the employer is named as a person, with no business name or legal form. Such rows are not loaded, counted or shown, and the mirrored ESDC files stay as published. Businesses named after their owner stay. The 2014 and 2015 lists name no occupation, so the rule cannot reach them. Coverage of caregiver hiring is incomplete by design.",
    fr: "Les ménages privés et les particuliers ne sont pas publiés. Un foyer privé n'est pas une entreprise, et la personne qui y embauche de l'aide n'est pas un employeur public. Les offres d'aide familiale et de soutien à domicile dont l'employeur est une personne sont écartées avant tout enregistrement. Les listes d'EDSC indiquent qu'elles excluent les noms de personnes, mais certains ménages y figurent : une inscription est écartée lorsque la profession est gardien d'enfants en milieu familial ou aide de maintien à domicile (CNP 4411, 4412, 44100 ou 44101) et que l'employeur est désigné par un nom de personne, sans nom d'entreprise ni forme juridique. Ces inscriptions ne sont ni chargées, ni comptées, ni affichées, et les fichiers d'EDSC reproduits restent tels qu'ils ont été publiés. Les entreprises qui portent le nom de leur propriétaire restent. Les listes de 2014 et de 2015 ne précisent aucune profession : la règle ne peut donc pas s'y appliquer. La couverture de l'embauche d'aides familiaux est incomplète par conception.",
  },
  "methodology.exclusions_workers": {
    en: "No worker is ever named. Applicant counts, resumes and contact details on a posting are not collected.",
    fr: "Aucun travailleur n'est jamais nommé. Le nombre de candidats, les curriculum vitæ et les coordonnées figurant sur une offre ne sont pas recueillis.",
  },
  "methodology.limits_text": {
    en: "The ESDC lists count positions on LMIAs. They do not count work permits issued or workers who arrived. The pending flag exists only for employers who advertised on Job Bank, which most streams require. Street addresses appear only when an employer entered one on Job Bank or an IRCC finding gives one; the quarterly lists give a city and postal code. Registry matches are by name and can be wrong.",
    fr: "Les listes d'EDSC comptent les postes visés par des EIMT. Elles ne comptent ni les permis de travail délivrés ni les travailleurs arrivés. La mention « EIMT demandée » n'existe que pour les employeurs qui ont annoncé au Guichet-Emplois, ce que la plupart des volets exigent. Les adresses municipales ne paraissent que si l'employeur en a inscrit une au Guichet-Emplois ou qu'un constat d'IRCC en donne une; les listes trimestrielles donnent une ville et un code postal. Les correspondances au registre se fondent sur le nom et peuvent être erronées.",
  },
  "methodology.versions_text": {
    en: "Indicator rules: v{rules}. Status lifecycle: v{rules}. Matching: v{rules}. Changes are listed on the {data} with the date and what was recomputed.",
    fr: "Règles des indicateurs : v{rules}. Cycle de vie des statuts : v{rules}. Jumelage : v{rules}. Les modifications sont inscrites sur la {data} avec la date et ce qui a été recalculé.",
  },
  "methodology.data_page": { en: "Data page", fr: "page Données" },

  // -- data and about ---------------------------------------------------------------
  "data.toc_downloads": { en: "Downloads", fr: "Téléchargements" },
  "data.toc_api": { en: "API", fr: "API" },
  "data.toc_licence": { en: "Licence", fr: "Licence" },
  "data.toc_changelog": { en: "Changelog", fr: "Journal des modifications" },
  "data.toc_reply": { en: "Right of Reply and Corrections", fr: "Droit de réponse et corrections" },
  "data.toc_about": { en: "About", fr: "À propos" },
  "data.lead": {
    en: "Everything on the site can be downloaded and rebuilt. Files are regenerated nightly and after each quarterly ESDC release.",
    fr: "Tout le contenu du site peut être téléchargé et reconstruit. Les fichiers sont régénérés chaque nuit et après chaque publication trimestrielle d'EDSC.",
  },
  "data.col_file": { en: "File", fr: "Fichier" },
  "data.col_contents": { en: "Contents", fr: "Contenu" },
  "data.col_updated": { en: "Updated", fr: "Mise à jour" },
  "data.file.pending_observations": {
    en: "Every nightly observation of a Job Bank posting with an LMIA flag: posting ID, employer, job, location, wage, dates, flag state, observed date",
    fr: "Chaque observation de nuit d'une offre du Guichet-Emplois portant une mention d'EIMT : identifiant de l'offre, employeur, emploi, lieu, salaire, dates, état de la mention, date d'observation",
  },
  "data.file.approved_quarterly": {
    en: "ESDC positive lists, all quarters since 2014, with a stable employer ID added",
    fr: "Listes positives d'EDSC, tous les trimestres depuis 2014, avec un identifiant d'employeur stable ajouté",
  },
  "data.file.refused_quarterly": {
    en: "ESDC negative lists, all quarters since 2014, with a stable employer ID added",
    fr: "Listes négatives d'EDSC, tous les trimestres depuis 2014, avec un identifiant d'employeur stable ajouté",
  },
  "data.file.employers": {
    en: "One row per merged employer: names seen, registry match and grade, location, current status, counts",
    fr: "Une ligne par employeur regroupé : noms relevés, correspondance au registre et niveau, lieu, statut actuel, nombres",
  },
  "data.file.indicators": {
    en: "Indicator state per employer with the rule version and the basis values",
    fr: "État des indicateurs par employeur, avec la version des règles et les valeurs de fondement",
  },
  "data.file.findings": {
    en: "IRCC non-compliant employers as published, joined to employer IDs",
    fr: "Employeurs non conformes d'IRCC tels que publiés, reliés aux identifiants d'employeurs",
  },
  "data.file.esdc_resources": {
    en: "Every ESDC file loaded, with its CKAN resource id, publication date, checksum and row count",
    fr: "Chaque fichier d'EDSC chargé, avec son identifiant de ressource CKAN, sa date de publication, sa somme de contrôle et son nombre de lignes",
  },
  "data.mirror": {
    en: "The original ESDC spreadsheets are mirrored unchanged under {mirror} with their SHA-256 checksums.",
    fr: "Les fichiers tableurs originaux d'EDSC sont reproduits sans modification sous {mirror} avec leurs sommes de contrôle SHA-256.",
  },
  "data.esdc_files": { en: "ESDC Files Loaded", fr: "Fichiers d'EDSC chargés" },
  "data.col_list": { en: "List", fr: "Liste" },
  "data.col_period": { en: "Period", fr: "Période" },
  "data.col_published": { en: "Published", fr: "Publication" },
  "data.col_rows": { en: "Rows", fr: "Lignes" },
  "data.col_loaded": { en: "Loaded", fr: "Chargement" },
  "data.no_files": { en: "No files loaded yet.", fr: "Aucun fichier chargé pour l'instant." },
  "data.list.positive": { en: "positive", fr: "positive" },
  "data.list.negative": { en: "negative", fr: "négative" },
  "data.api_text": { en: "Read-only JSON, no key. Employer listings are in the downloads.", fr: "JSON en lecture seule, sans clé. Les listes d'employeurs se trouvent dans les téléchargements." },
  "data.col_endpoint": { en: "Endpoint", fr: "Point de terminaison" },
  "data.col_returns": { en: "Returns", fr: "Renvoie" },
  "data.api.stats": {
    en: "Headline counts, breakdowns, recent lists and the as-of dates",
    fr: "Chiffres clés, répartitions, listes récentes et dates de référence",
  },
  "data.api.employer": { en: "Profile: records, indicators, registry, findings", fr: "Profil : dossiers, indicateurs, registre, constats" },
  "data.api.pending": { en: "Pending postings posted on or after a date", fr: "Offres en attente publiées à une date donnée ou après" },
  "data.api.clusters": {
    en: "Record counts by postal area with centroid coordinates",
    fr: "Nombre de dossiers par secteur postal, avec les coordonnées du centre",
  },
  "data.api.area": { en: "Records in one postal area, latest scope", fr: "Dossiers d'un secteur postal, période récente" },
  "data.api.facets": {
    en: "Record counts by status and province for both search scopes, and every search file's size",
    fr: "Nombre de dossiers par statut et par province pour les deux périodes de recherche, et taille de chaque fichier de recherche",
  },
  "data.api.files": {
    en: "The search rows, as the search page loads them (file list in the facets)",
    fr: "Les lignes de recherche, telles que la page de recherche les charge (liste des fichiers dans les facettes)",
  },
  "data.licence": { en: "Licence and Attribution", fr: "Licence et attribution" },
  "data.code_licence": { en: "The site's own code, text and design are published for inspection and are not licensed for reuse or for running another site; the data licences above are unaffected.", fr: "Le code, les textes et le design du site sont publiés pour consultation et ne sont pas concédés sous licence pour réutilisation ni pour exploiter un autre site; les licences des données ci-dessus demeurent inchangées." },
  "data.licence_text": {
    en: "Each file and field keeps the licence or terms of the source it comes from. The site does not relicense any of them.",
    fr: "Chaque fichier et chaque champ garde la licence ou les conditions de la source dont il provient. Le site n'en modifie aucune.",
  },
  "data.col_material": { en: "Files and fields", fr: "Fichiers et champs" },
  "data.col_terms": { en: "Licence or terms", fr: "Licence ou conditions" },
  "data.lic.ogl": { en: "Open Government Licence, Canada", fr: "Licence du gouvernement ouvert, Canada" },
  "data.lic.canada_terms": { en: "Government of Canada terms of use (canada.ca)", fr: "conditions d'utilisation du gouvernement du Canada (canada.ca)" },
  "data.lic.cc": { en: "CC BY-NC-SA 4.0", fr: "CC BY-NC-SA 4.0" },
  "data.lic.esdc": {
    en: "approved_quarterly.csv, refused_quarterly.csv, esdc_resources.csv and the mirrored ESDC files; in employers.csv, the approved and refused counts and the names and places from ESDC's lists; federal corporation details on profiles (Corporations Canada extract)",
    fr: "approved_quarterly.csv, refused_quarterly.csv, esdc_resources.csv et les fichiers d'EDSC reproduits; dans employers.csv, les nombres d'approbations et de refus ainsi que les noms et les lieux tirés des listes d'EDSC; renseignements sur les sociétés fédérales dans les profils (extrait de Corporations Canada)",
  },
  "data.lic.esdc_terms": {
    en: "{ogl}: reuse, commercial or not, with attribution.",
    fr: "{ogl} : réutilisation, commerciale ou non, avec mention de la source.",
  },
  "data.lic.jobbank": {
    en: "pending_observations.csv; in employers.csv, pending_count and the name, place and street of an employer known only from Job Bank or whose street comes from a posting",
    fr: "pending_observations.csv; dans employers.csv, pending_count ainsi que le nom, le lieu et l'adresse d'un employeur connu seulement par le Guichet-Emplois ou dont l'adresse provient d'une offre",
  },
  "data.lic.jobbank_terms": {
    en: "Under the {terms}: non-commercial reproduction with attribution; commercial redistribution needs ESDC's written permission.",
    fr: "Selon les {terms} : reproduction non commerciale avec mention de la source; la redistribution commerciale exige la permission écrite d'EDSC.",
  },
  "data.lic.ircc": {
    en: "findings.csv (IRCC's list of non-compliant employers); in employers.csv, finding_count and a street taken from a finding",
    fr: "findings.csv (liste des employeurs non conformes d'IRCC); dans employers.csv, finding_count et une adresse tirée d'un constat",
  },
  "data.lic.ircc_terms": {
    en: "Under the same {terms}: non-commercial reproduction with attribution; commercial redistribution needs prior written permission.",
    fr: "Selon les mêmes {terms} : reproduction non commerciale avec mention de la source; la redistribution commerciale exige une permission écrite préalable.",
  },
  "data.lic.quebec": {
    en: "Quebec register details on profiles and in the API: enterprise number, legal name, form, status and registration date",
    fr: "Renseignements du registre du Québec dans les profils et l'API : numéro d'entreprise, dénomination, forme juridique, statut et date d'immatriculation",
  },
  "data.lic.quebec_terms": {
    en: "{cc}: non-commercial use, shared under the same licence, without the Registraire's endorsement. Cite as: REGISTRAIRE DES ENTREPRISES. Registre des entreprises, [Jeu de données], dans Données Québec.",
    fr: "{cc} : usage non commercial, partage sous la même licence, sans approbation du Registraire. Citation : REGISTRAIRE DES ENTREPRISES. Registre des entreprises, [Jeu de données], dans Données Québec.",
  },
  "data.lic.statcan": {
    en: "Statistics Canada figures: the Labour Force Survey and job vacancy tables (14-10-0459-01, 14-10-0444-01), the NOC 2021 classification and the 2021 Census boundary files, in the indicators and on the occupation and place pages",
    fr: "Chiffres de Statistique Canada : tableaux de l'Enquête sur la population active et des postes vacants (14-10-0459-01, 14-10-0444-01), classification CNP 2021 et fichiers des limites du Recensement de 2021, dans les indicateurs et les pages des professions et des lieux",
  },
  "data.lic.statcan_terms": {
    en: "{statcan}. Source: Statistics Canada, tables 14-10-0459-01 and 14-10-0444-01, NOC 2021 Version 1.0 and the 2021 Census boundary files. Reproduced and distributed on an \"as is\" basis with the permission of Statistics Canada. Figures the site calculates from them are adapted from Statistics Canada; this does not constitute an endorsement by Statistics Canada of this product.",
    fr: "{statcan}. Source : Statistique Canada, tableaux 14-10-0459-01 et 14-10-0444-01, CNP 2021 version 1.0 et fichiers des limites du Recensement de 2021. Reproduit et diffusé « tel quel » avec la permission de Statistique Canada. Les chiffres que le site en tire sont adaptés de Statistique Canada; ceci ne constitue pas une approbation de ce produit par Statistique Canada.",
  },
  "data.lic.computed": {
    en: "indicators.csv, and in employers.csv the status, dates, indicator count and registry grade",
    fr: "indicators.csv et, dans employers.csv, le statut, les dates, le nombre d'indicateurs et le niveau de correspondance au registre",
  },
  "data.lic.computed_terms": {
    en: "Worked out by this site from the sources in this table; each figure keeps the terms of the source it rests on.",
    fr: "Calculés par le site à partir des sources de ce tableau; chaque chiffre garde les conditions de la source sur laquelle il repose.",
  },
  "data.lic.geonames": { en: "Postal-area centroids for the maps", fr: "Centres des secteurs postaux des cartes" },
  "data.lic.geonames_terms": { en: "GeoNames, under CC BY 4.0.", fr: "GeoNames, sous licence CC BY 4.0." },
  "data.dl.canada": { en: "canada.ca terms, non-commercial", fr: "conditions de canada.ca, usage non commercial" },
  "data.dl.mixed": { en: "By source", fr: "Selon la source" },
  "data.sources_text": {
    en: "The wage and unemployment indicators use {wages} (Open Government Licence, Canada), Statistics Canada's {lfs} and the {boundaries}, used under the {statcan}.",
    fr: "Les indicateurs salarial et de chômage utilisent les {wages} (Licence du gouvernement ouvert, Canada), le {lfs} de Statistique Canada et les {boundaries}, utilisés sous la {statcan}.",
  },
  "data.src.wages": { en: "Job Bank wages", fr: "salaires du Guichet-Emplois" },
  "data.src.lfs": { en: "Labour Force Survey table 14-10-0459-01", fr: "tableau 14-10-0459-01 de l'Enquête sur la population active" },
  "data.src.boundaries": { en: "2021 Census boundary files", fr: "fichiers des limites du Recensement de 2021" },
  "data.src.statcan_licence": { en: "Statistics Canada Open Licence", fr: "Licence ouverte de Statistique Canada" },
  "data.program_text": {
    en: "The {program} page reads three ESDC pages on canada.ca each night (LMIA processing times, the low-wage refusal-to-process list by census metropolitan area, and the provincial and territorial wage thresholds), reproduced under the {terms}; the low-wage stream indicator reads the lists.",
    fr: "La page {program} relève chaque nuit trois pages d'EDSC sur canada.ca (délais de traitement des EIMT, liste des refus de traitement à bas salaire par région métropolitaine de recensement et seuils salariaux provinciaux et territoriaux), reproduites conformément aux {terms}; l'indicateur du volet des postes à bas salaire lit les listes.",
  },
  "data.crawl_text": {
    en: "The nightly check sends one request at a time to Job Bank under a named user agent with a contact address. The run stops if Job Bank returns errors.",
    fr: "La vérification de nuit envoie une requête à la fois au Guichet-Emplois sous un agent utilisateur nommé, avec une adresse de contact. L'exécution s'arrête si le Guichet-Emplois renvoie des erreurs.",
  },
  "data.col_change": { en: "Change", fr: "Modification" },
  "data.col_recomputed": { en: "Recomputed", fr: "Recalculé" },
  "data.change_drafted": {
    en: "Site structure drafted. Indicator rules v{rules}. ESDC lists loaded through {period}. Federal corporations matched by name.",
    fr: "Structure du site ébauchée. Règles des indicateurs v{rules}. Listes d'EDSC chargées jusqu'au {period}. Sociétés fédérales jumelées par nom.",
  },
  "data.recomputed_all": { en: "All", fr: "Tout" },
  "data.change_wages": {
    en: "Indicator rules v{rules}. Wage at the prevailing-wage floor and low-wage stream in a high-unemployment region are evaluated, from Job Bank wages, the Labour Force Survey and the 2021 Census boundaries.",
    fr: "Règles des indicateurs v{rules}. Le salaire au plancher du salaire courant et le volet des postes à bas salaire dans une région à chômage élevé sont évalués, à partir des salaires du Guichet-Emplois, de l'Enquête sur la population active et des limites du Recensement de 2021.",
  },
  "data.change_matching": {
    en: "Employer matching: the legal name before a trade-name marker (dba, o/a, operating as) is the identity; dots in abbreviations, accents, initials and numbered company names are written one way. Some profiles merged and some employer IDs changed. IRCC findings supply a street and names seen. Quebec enterprises matched to the Quebec register.",
    fr: "Jumelage des employeurs : la dénomination sociale qui précède une mention de nom commercial (dba, o/a, operating as) sert d'identité; les points des abréviations, les accents, les initiales et les noms de sociétés à numéro s'écrivent d'une seule façon. Certains profils ont été regroupés et certains identifiants d'employeur ont changé. Les constats d'IRCC fournissent une adresse et des noms relevés. Entreprises du Québec jumelées au registre du Québec.",
  },
  "data.recomputed_profiles": { en: "Employer profiles, registry matches", fr: "Profils d'employeurs, correspondances aux registres" },
  "data.recomputed_wages": { en: "Wage at floor, low-wage stream", fr: "Salaire au plancher, volet des postes à bas salaire" },
  "data.runs": { en: "Recent Runs", fr: "Exécutions récentes" },
  "data.col_run": { en: "Run", fr: "Exécution" },
  "data.run_time": { en: "{date} {hh}:{mm} UTC", fr: "{date} {hh} h {mm} UTC" },
  "occ.toc_title": { en: "Categories", fr: "Catégories" },
  "occ.filter_label": { en: "Find an occupation", fr: "Trouver une profession" },
  "occ.filter_placeholder": { en: "Title or NOC code, e.g. cook or 63200", fr: "Titre ou code CNP, p. ex. cuisinier ou 63200" },
  "occ.filter_none": { en: "No occupation matches.", fr: "Aucune profession ne correspond." },
  "occ.filter_count": { en: "{n} of {total} occupations", fr: "{n} professions sur {total}" },
  "data.col_stage": { en: "Stage", fr: "Étape" },
  "data.col_detail": { en: "Detail", fr: "Détail" },
  "data.col_new_rows": { en: "New rows", fr: "Nouvelles lignes" },
  "data.col_ok": { en: "OK", fr: "OK" },
  "data.no_runs": { en: "No runs recorded yet.", fr: "Aucune exécution consignée pour l'instant." },
  "data.reply": { en: "Right of Reply", fr: "Droit de réponse" },
  "data.reply_text": {
    en: "An employer's statement is posted unedited on its profile with the date received, once the sender is verified against the contact details on the Job Bank posting or registry record.",
    fr: "La déclaration d'un employeur est publiée sans modification sur son profil, avec la date de réception, une fois l'expéditeur vérifié à l'aide des coordonnées de l'offre du Guichet-Emplois ou du dossier du registre.",
  },
  "data.reply_how": {
    en: 'Open the employer\'s profile and choose "{button}".',
    fr: "Ouvrez le profil de l'employeur et choisissez « {button} ».",
  },
  "data.corrections_text": {
    en: "Anyone can report a wrong match, a stale record or a misfiring indicator. Requests with an email address get a reply. Changes appear in the profile's corrections log after review.",
    fr: "Toute personne peut signaler une mauvaise correspondance, un dossier périmé ou un indicateur erroné. Les demandes accompagnées d'une adresse de courriel reçoivent une réponse. Les modifications paraissent dans le journal des corrections du profil après examen.",
  },
  "data.about_records": {
    en: "This site collects public records on Labour Market Impact Assessments. They show which employers are applying to hire temporary foreign workers, where and when, and which applications were approved or refused. The project is independent of any government, employer or union and accepts no advertising.",
    fr: "Ce site rassemble des dossiers publics sur les études d'impact sur le marché du travail. Ils montrent quels employeurs demandent à embaucher des travailleurs étrangers temporaires, où et quand, et quelles demandes ont été approuvées ou refusées. Le projet est indépendant de tout gouvernement, employeur ou syndicat et n'accepte aucune publicité.",
  },
  "data.about_enforcement": {
    en: "Records are government data reproduced as published. Enforcement belongs to Service Canada and IRCC, and every profile links to their reporting channels.",
    fr: "Les dossiers sont des données gouvernementales reproduites telles que publiées. L'application de la loi relève de Service Canada et d'IRCC, et chaque profil renvoie à leurs moyens de signalement.",
  },
  "data.about_contact": {
    en: "The {form} is the only way to reach the operator. The site has no visitor accounts and sets no tracking cookies. Correction and response submissions are kept only as long as needed to act on them.",
    fr: "Le {form} est le seul moyen de joindre l'exploitant. Le site n'a pas de comptes de visiteurs et ne dépose aucun témoin de suivi. Les demandes de correction et les réponses ne sont conservées que le temps nécessaire pour y donner suite.",
  },
  "data.about_form": { en: "corrections form", fr: "formulaire de correction" },

  // -- support ----------------------------------------------------------------------
  "support.title": { en: "Support the Site", fr: "Soutenir le site" },
  "support.toc_holds": { en: "What the Site Holds Today", fr: "Ce que le site contient aujourd'hui" },
  "support.toc_costs": { en: "What It Costs Today", fr: "Ce qu'il coûte aujourd'hui" },
  "support.toc_tiers": { en: "Upgrade Paths", fr: "Paliers de mise à niveau" },
  "support.toc_beyond": { en: "Beyond the Costs", fr: "Au-delà des coûts" },
  "support.toc_donation": { en: "Where a Donation Goes", fr: "Où va un don" },
  "support.toc_give": { en: "How to Give", fr: "Comment donner" },
  "support.toc_transparency": { en: "Transparency", fr: "Transparence" },
  "support.toc_law": { en: "The Records and the Law", fr: "Les dossiers et la loi" },
  "support.lead": {
    en: "The site is free to use, carries no advertising and sells nothing. Support is voluntary and brings no perks, early access or say in what is published. The site is not a registered charity and cannot issue tax receipts.",
    fr: "Le site est gratuit, ne contient aucune publicité et ne vend rien. Le soutien est volontaire et ne donne droit à aucun avantage, accès anticipé ou droit de regard sur ce qui est publié. Le site n'est pas un organisme de bienfaisance enregistré et ne peut pas délivrer de reçus fiscaux.",
  },
  "support.holds_lists": { en: "Every ESDC quarterly list since {year} is loaded{through}.", fr: "Toutes les listes trimestrielles d'EDSC depuis {year} sont chargées{through}." },
  "support.holds_through": { en: ", through {period}", fr: ", jusqu'au {period}" },
  "support.holds_profiles": {
    en: "Employer profiles carry each employer's full history{count}.",
    fr: "Les profils d'employeurs présentent l'historique complet de chaque employeur{count}.",
  },
  "support.holds_employers": { en: " ({n} employers)", fr: " ({n} employeurs)" },
  "support.holds_search": {
    en: "Search covers pending postings and the latest quarter, or on request {scope} in the browser.",
    fr: "La recherche couvre les offres en attente et le dernier trimestre, ou sur demande {scope} dans le navigateur.",
  },
  "support.holds_since": { en: "everything since {period}", fr: "l'ensemble des dossiers depuis le {period}" },
  "support.holds_longer": { en: "a longer history", fr: "un historique plus long" },
  "support.holds_older": { en: "{older} are in the {downloads} only.", fr: "{older} se trouvent seulement dans les {downloads}." },
  "support.holds_before": { en: "Records before {period}", fr: "Les dossiers antérieurs au {period}" },
  "support.holds_older_records": { en: "Older records", fr: "Les dossiers plus anciens" },
  "support.holds_matched": {
    en: "The IRCC non-compliance list and the federal corporations registry are matched nightly.",
    fr: "La liste des employeurs non conformes d'IRCC et le registre des sociétés fédérales sont jumelés chaque nuit.",
  },
  "support.holds_refresh": { en: "One refresh a day, at {time}.", fr: "Une mise à jour par jour, à {time}." },
  "support.refresh_midnight": { en: "midnight UTC", fr: "minuit UTC" },
  "support.refresh_hour": { en: "{hh}:00 UTC", fr: "{hh} h 00 UTC" },
  "support.limits": { en: "Current Limits", fr: "Limites actuelles" },
  "support.limit_views": { en: "{n} page views a day.", fr: "{n} pages vues par jour." },
  "support.limit_paid": {
    en: "Since {date} the site runs on Cloudflare's Workers Paid plan: about {n} page views a month are included, with no daily ceiling. The operator pays for the plan; support received does not cover it yet.",
    fr: "Depuis le {date}, le site fonctionne avec le forfait Workers Paid de Cloudflare : environ {n} pages vues par mois sont incluses, sans plafond quotidien. L'exploitant paie le forfait; le soutien reçu ne le couvre pas encore.",
  },
  "support.limit_search": {
    en: "No server-side search of the full history; the long search scope is a multi-megabyte browser download.",
    fr: "Aucune recherche côté serveur dans l'historique complet; la période de recherche longue est un téléchargement de plusieurs mégaoctets dans le navigateur.",
  },
  "support.limit_storage": { en: "{n} GB of file storage.", fr: "{n} Go de stockage de fichiers." },
  "support.costs_note": {
    en: "Amounts are monthly and in Canadian dollars unless stated.",
    fr: "Les montants sont mensuels et en dollars canadiens, sauf indication contraire.",
  },
  "support.bar_domain": { en: "Domain registration", fr: "Enregistrement du domaine" },
  "support.bar_workers": { en: "Workers Paid plan (paid by the operator for now)", fr: "Forfait Workers Paid (payé par l'exploitant pour l'instant)" },
  "support.bar_hosting": { en: "Storage and database", fr: "Stockage et base de données" },
  "support.bar_github": { en: "GitHub task fees", fr: "Frais de tâches GitHub" },
  "support.bar_x": { en: "Daily post on X (optional)", fr: "Publication quotidienne sur X (facultatif)" },
  "support.bar_total": { en: "Total", fr: "Total" },
  "support.costs_detail": {
    en: "Domain registration is {domain} a year. Since {since} the site runs on the Workers Paid plan, {workersUsd} a month plus an allowance for tax and usage, about {workers}; the operator pays for it until support covers it. File storage and the database stay on free tiers. The nightly refresh runs as a scheduled task on GitHub, and runner minutes past the monthly allowance are billed per minute, about {github} a month. The daily post on X is billed by X per message ({usd} without a link), about {monthly} a month. It is optional and the site runs without it.",
    fr: "L'enregistrement du domaine coûte {domain} par année. Depuis le {since}, le site fonctionne avec le forfait Workers Paid, {workersUsd} par mois plus une provision pour la taxe et l'utilisation, soit environ {workers}; l'exploitant le paie jusqu'à ce que le soutien le couvre. Le stockage de fichiers et la base de données restent sur des forfaits gratuits. La mise à jour nocturne s'exécute comme tâche planifiée sur GitHub, et les minutes d'exécution au-delà de l'allocation mensuelle sont facturées à la minute, soit environ {github} par mois. La publication quotidienne sur X est facturée par X à chaque message ({usd} sans lien), soit environ {monthly} par mois. Elle est facultative et le site fonctionne sans elle.",
  },
  "support.tiers_summary": {
    en: "Monthly cost of every tier: {target}. Monthly support received: {support}. Reserve held: {months} of {goal}.",
    fr: "Coût mensuel de tous les paliers : {target}. Soutien mensuel reçu : {support}. Réserve détenue : {months} sur {goal}.",
  },
  "support.tiers_note": {
    en: "Each tier assumes the ones above it; support is measured against the cumulative cost. Support received is the last 30 days of payments.",
    fr: "Chaque palier suppose ceux qui le précèdent; le soutien est mesuré par rapport au coût cumulatif. Le soutien reçu correspond aux paiements des 30 derniers jours.",
  },
  "support.col_tier": { en: "Tier", fr: "Palier" },
  "support.col_monthly_cost": { en: "Monthly cost", fr: "Coût mensuel" },
  "support.col_pays_for": { en: "What it pays for", fr: "Ce qu'il finance" },
  "support.col_against": { en: "Monthly support against cost", fr: "Soutien mensuel par rapport au coût" },
  "support.of": { en: "{part} of {whole}", fr: "{part} sur {whole}" },
  "support.status.funded": { en: "Funded", fr: "Financé" },
  "support.status.partly": { en: "Partly funded", fr: "Partiellement financé" },
  "support.status.not_yet": { en: "Not yet funded", fr: "Pas encore financé" },
  "support.status.in_place": { en: "In place, paid by the operator", fr: "En place, payé par l'exploitant" },
  "support.tier.baseline.name": { en: "Baseline", fr: "Base" },
  "support.tier.baseline.unlocks": {
    en: "Keeps the site online at its own address, with hosting on free tiers, the nightly refresh on GitHub, and the daily post on X.",
    fr: "Garde le site en ligne à sa propre adresse, avec un hébergement sur des forfaits gratuits, la mise à jour nocturne sur GitHub et la publication quotidienne sur X.",
  },
  "support.tier.workers_paid.name": { en: "Workers Paid plan", fr: "Forfait Workers Paid" },
  "support.tier.workers_paid.unlocks": {
    en: "Lifts the daily page-view ceiling and the per-request compute limit, and is the prerequisite for hosted search.",
    fr: "Lève le plafond quotidien de pages vues et la limite de calcul par requête, et constitue le préalable à la recherche hébergée.",
  },
  "support.tier.hosted_search.name": { en: "Hosted search", fr: "Recherche hébergée" },
  "support.tier.hosted_search.unlocks": {
    en: "A hosted database, so the full history since {year} is searchable on the site with no large download.",
    fr: "Une base de données hébergée, pour que l'historique complet depuis {year} soit consultable sur le site sans gros téléchargement.",
  },
  "support.tier.storage.name": { en: "Storage reserve", fr: "Réserve de stockage" },
  "support.tier.storage.unlocks": {
    en: "Pays for file storage past the free {free} GB, about {gb} GB more.",
    fr: "Paie le stockage de fichiers au-delà des {free} Go gratuits, soit environ {gb} Go de plus.",
  },
  "support.tier.x_verification.name": { en: "X verification", fr: "Vérification sur X" },
  "support.tier.x_verification.unlocks": {
    en: "The verified badge on the site's X account, shown beside its name on every daily post. Optional.",
    fr: "Le badge de vérification du compte X du site, affiché à côté de son nom dans chaque publication quotidienne. Facultatif.",
  },
  "support.months_one": { en: "{n} month", fr: "{n} mois" },
  "support.months_many": { en: "{n} months", fr: "{n} mois" },
  "support.cents_one": { en: "{n} cent", fr: "{n} cent" },
  "support.cents_many": { en: "{n} cents", fr: "{n} cents" },
  "support.reserve_goal": {
    en: "The reserve goal is {goal} of the full monthly cost, about {about}.",
    fr: "L'objectif de réserve est de {goal} du coût mensuel complet, soit environ {about}.",
  },
  "support.estimates": {
    en: "Monthly costs are estimates. The Workers Paid plan lists at {usd} a month, about {cad}; its row adds an allowance for sales tax and usage above the included amounts. Extra storage costs about {cents} per GB a month.",
    fr: "Les coûts mensuels sont des estimations. Le forfait Workers Paid est affiché à {usd} par mois, soit environ {cad}; sa ligne ajoute une provision pour la taxe de vente et l'utilisation au-delà des quantités incluses. Le stockage supplémentaire coûte environ {cents} par Go par mois.",
  },
  "support.met": {
    en: "Monthly support now covers every tier and the reserve holds {goal}, so the site needs nothing further.",
    fr: "Le soutien mensuel couvre maintenant tous les paliers et la réserve contient {goal} : le site n'a besoin de rien de plus.",
  },
  "support.beyond_text": {
    en: "The figures above are the whole hosting budget. Once monthly support covers the monthly cost of every tier and {goal} are held in reserve, the site needs nothing further. Anything given beyond that point is personal support for the person who runs the site. It is greatly appreciated, and it is not spent on hosting or database upgrades.",
    fr: "Les chiffres ci-dessus constituent tout le budget d'hébergement. Une fois que le soutien mensuel couvre le coût mensuel de tous les paliers et que {goal} sont détenus en réserve, le site n'a besoin de rien de plus. Tout don au-delà de ce point est un soutien personnel à la personne qui gère le site. Il est très apprécié, et il n'est pas dépensé pour l'hébergement ni pour des mises à niveau de la base de données.",
  },
  "support.gift_split": { en: "A {gift} gift, split:", fr: "Répartition d'un don de {gift} :" },
  "support.split_aria": {
    en: "Card processing fee {fee}, toward the monthly cost {net}",
    fr: "Frais de traitement par carte {fee}, contribution au coût mensuel {net}",
  },
  "support.fee_line": { en: "Card processing fee: {fee} ({rate})", fr: "Frais de traitement par carte : {fee} ({rate})" },
  "support.net_line": { en: "Toward the monthly cost: {net}", fr: "Contribution au coût mensuel : {net}" },
  "support.fee_rate": { en: "{pct} percent plus {cents} cents", fr: "{pct} % plus {cents} cents" },
  "support.donate_default": { en: "Give through the payment page", fr: "Donner par la page de paiement" },
  "support.card_note": {
    en: "Card details are entered on an outside payment page and never reach this site.",
    fr: "Les données de carte sont saisies sur une page de paiement externe et ne parviennent jamais à ce site.",
  },
  "support.closed": { en: "Donations are not open yet.", fr: "Les dons ne sont pas encore ouverts." },
  "support.col_quarter": { en: "Quarter", fr: "Trimestre" },
  "support.col_received": { en: "Received", fr: "Reçu" },
  "support.col_spent": { en: "Spent", fr: "Dépensé" },
  "support.col_reserve": { en: "Reserve", fr: "Réserve" },
  "support.no_donations": { en: "No donations yet", fr: "Aucun don pour l'instant" },
  "support.transparency_text": {
    en: "The table updates itself from the payment page's notices, which the site keeps as amount, time and kind only; names and messages are not stored. Spent is the monthly cost for each month started. A shortfall is paid by the person who runs the site.",
    fr: "Le tableau se met à jour à partir des avis de la page de paiement, que le site conserve sous forme de montant, d'heure et de type seulement; les noms et les messages ne sont pas conservés. « Dépensé » correspond au coût mensuel de chaque mois commencé. Un déficit est comblé par la personne qui gère le site.",
  },
  "support.law_text": {
    en: "The LMIA employer lists come from the Government of Canada's open data under the Open Government Licence, Canada, which permits reuse. Job Bank content is Government of Canada material, reproduced here for non-commercial public use with attribution. A donation does not buy access to any record.",
    fr: "Les listes d'employeurs visés par une EIMT proviennent des données ouvertes du gouvernement du Canada, sous la Licence du gouvernement ouvert, Canada, qui en permet la réutilisation. Le contenu du Guichet-Emplois est du matériel du gouvernement du Canada, reproduit ici avec attribution pour un usage public non commercial. Un don ne donne accès à aucun dossier.",
  },

  // -- indicator basis sentences ------------------------------------------------------
  // The pipeline writes each indicator's basis as an English sentence
  // (pipeline/lmia_pipeline/indicators.py). These are its sentence forms;
  // basisText() matches a sentence against the English form and fills the
  // French one. A sentence that matches none stays in English.
  "basis.no_wage_table": { en: "Prevailing wage table not yet loaded.", fr: "Table des salaires courants pas encore chargée." },
  "basis.no_unemployment_table": { en: "Regional unemployment table not yet loaded.", fr: "Table du chômage régional pas encore chargée." },
  "basis.no_low_wage": { en: "No low-wage stream records.", fr: "Aucun dossier dans le volet des postes à bas salaire." },
  "basis.no_posting": { en: "No Job Bank posting.", fr: "Aucune offre du Guichet-Emplois." },
  "basis.wage_no_noc": {
    en: "No posting page parsed yet, so the occupation is unknown.",
    fr: "Aucune page d'offre analysée pour l'instant : la profession est donc inconnue.",
  },
  "basis.wage_no_region": {
    en: "No posting has a postal code that places it in an economic region.",
    fr: "Aucune offre n'a un code postal qui la situe dans une région économique.",
  },
  "basis.wage_no_median": { en: "No Job Bank median for NOC {noc}.", fr: "Aucune médiane du Guichet-Emplois pour la CNP {noc}." },
  "basis.wage_unit": {
    en: "No posted wage matches the hourly or yearly unit of the Job Bank median.",
    fr: "Aucun salaire affiché n'est dans l'unité horaire ou annuelle de la médiane du Guichet-Emplois.",
  },
  // {area} is "the X economic region (Province)", "Province (provincial
  // figure)" or "Canada (national figure)"; frValue() translates each form.
  "basis.wage_at_floor": {
    en: "Posting {id}: posted minimum ${posted}/{unit} is within 1 percent of the Job Bank median ${median}/{unit2} for NOC {noc} in {area}, wage table dated {date}.",
    fr: "Offre {id} : salaire minimum affiché de {posted} $/{unit}, à 1 % ou moins de la médiane du Guichet-Emplois de {median} $/{unit2} pour la CNP {noc} ({area}), table des salaires du {date}.",
  },
  "basis.wage_closest": {
    en: "Closest of {n} posting(s) compared: posting {id}, posted minimum ${posted}/{unit} against the Job Bank median ${median}/{unit2} for NOC {noc} in {area}, wage table dated {date}.",
    fr: "Offre la plus proche parmi {n} offre(s) comparée(s) : offre {id}, salaire minimum affiché de {posted} $/{unit} pour une médiane du Guichet-Emplois de {median} $/{unit2}, CNP {noc} ({area}), table des salaires du {date}.",
  },
  "basis.low_wage_out_of_scope": {
    en: "No low-wage approvals from {start} on.",
    fr: "Aucune approbation dans le volet des postes à bas salaire depuis le {start}.",
  },
  "basis.low_wage_unplaced": {
    en: "The low-wage approvals could not be placed in an area with a published unemployment rate.",
    fr: "Les approbations dans le volet des postes à bas salaire n'ont pu être situées dans une région dont le taux de chômage est publié.",
  },
  "basis.low_wage_high": {
    en: "Low Wage stream approval in {period}; the {cma} CMA unemployment rate was {rate} percent for the three months ending {month} and {rate2} percent for the three months ending {month2} (Statistics Canada LFS).",
    fr: "Approbation dans le volet des postes à bas salaire, {period}; taux de chômage de {rate} % pour les trois mois se terminant en {month} et de {rate2} % pour les trois mois se terminant en {month2}, région métropolitaine de recensement : {cma} (EPA de Statistique Canada).",
  },
  "basis.low_wage_none_high": {
    en: "{n} low-wage positive-list row(s) from {start} on; none in a census metropolitan area at or above 6 percent in both three-month periods checked.",
    fr: "{n} inscription(s) sur la liste positive dans le volet des postes à bas salaire depuis le {start}; aucune dans une région métropolitaine de recensement à 6 % ou plus pendant les deux périodes de trois mois vérifiées.",
  },
  // Rules 0.3: a quarter whose two refusal-to-process lists are stored is
  // judged on the rates ESDC published, and the sentence says so.
  "basis.low_wage_lists_high": {
    en: "Low Wage stream approval in {period}; ESDC's refusal-to-process lists gave the {cma} CMA {rate} percent from {start} and {rate2} percent from {start2}.",
    fr: "Approbation dans le volet des postes à bas salaire, {period}; les listes de refus de traitement d'EDSC donnaient {rate} % à compter du {start} et {rate2} % à compter du {start2}, région métropolitaine de recensement : {cma}.",
  },
  "basis.low_wage_lists_none": {
    en: "{n} low-wage positive-list row(s) from {start} on; none in a census metropolitan area at or above 6 percent in both periods checked: {lists} against ESDC's published refusal-to-process lists, {lfs} against Statistics Canada LFS rates.",
    fr: "{n} inscription(s) sur la liste positive dans le volet des postes à bas salaire depuis le {start}; aucune dans une région métropolitaine de recensement à 6 % ou plus pendant les deux périodes vérifiées : {lists} selon les listes de refus de traitement publiées par EDSC, {lfs} selon les taux de l'EPA de Statistique Canada.",
  },
  "basis.no_registry": { en: "No registry match yet.", fr: "Aucune correspondance au registre pour l'instant." },
  "basis.nothing_to_compare": {
    en: "No pending posting or list record to compare against.",
    fr: "Aucune offre en attente ni inscription de liste à comparer.",
  },
  "basis.registered_new": {
    en: "Registered {reg}, first record {first} ({days} days).",
    fr: "Date d'enregistrement : {reg}; premier dossier : {first} ({days} jours).",
  },
  "basis.registered_after": {
    en: "Registered {reg}, after the first record ({first}).",
    fr: "Date d'enregistrement : {reg}, après le premier dossier ({first}).",
  },
  "basis.registered_before": {
    en: "Registered {reg}, {days} days before the first record.",
    fr: "Date d'enregistrement : {reg}, {days} jours avant le premier dossier.",
  },
  "basis.no_positive": { en: "No positive-list rows.", fr: "Aucune inscription sur la liste positive." },
  "basis.repeat_run": {
    en: "NOC {noc}: positive list in {run} consecutive quarters ({start} to {end}).",
    fr: "CNP {noc} : liste positive pendant {run} trimestres consécutifs ({start} à {end}).",
  },
  "basis.longest_run": {
    en: "Longest run of consecutive quarters for one occupation: {run}.",
    fr: "Plus longue série de trimestres consécutifs pour une profession : {run}.",
  },
  "basis.volume_approved": { en: "{top} positions approved in {period}.", fr: "{top} postes approuvés, {period}." },
  "basis.volume_median": {
    en: "{top} positions in {period}, against a median quarter of {median}.",
    fr: "{top} postes, {period}, pour un trimestre médian de {median}.",
  },
  "basis.volume_largest": { en: "Largest quarter: {top} positions ({period}).", fr: "Trimestre le plus élevé : {top} postes ({period})." },
  "basis.no_negative": { en: "No negative-list rows.", fr: "Aucune inscription sur la liste négative." },
  "basis.refused_reposted": {
    en: "Refused in {period} (list published {published}); new posting observed {seen}.",
    fr: "Refus, {period} (liste publiée le {published}); nouvelle offre observée le {seen}.",
  },
  "basis.refusals_no_repost": {
    en: "{n} refusal record(s), no new posting within {days} days of publication.",
    fr: "{n} dossier(s) de refus, aucune nouvelle offre dans les {days} jours suivant la publication.",
  },
  "home.week_caption": { en: "Job Bank postings carrying the \"LMIA requested\" flag, newest first.", fr: "Offres d'emploi du Guichet-Emplois portant la mention « EIMT demandée », les plus récentes en premier." },
  "home.pending_by_prov": { en: "Pending by province, all {n} postings.", fr: "En attente par province, {n} offres au total." },
  "data.api_limits": { en: "Limits per address: 60 API requests a minute, 10 downloads a minute. Above that the site answers 429 until the minute passes. Bulk users should take the downloads rather than the API.", fr: "Limites par adresse : 60 requêtes API par minute, 10 téléchargements par minute. Au-delà, le site répond 429 jusqu'à la fin de la minute. Pour un usage en masse, prenez les téléchargements plutôt que l'API." },
  "employer.minimap_aria": { en: "Map of postal area {fsa}, centred on its centroid", fr: "Carte du secteur postal {fsa}, centrée sur son centroïde" },
  "employer.map_credit": { en: "Map: OpenStreetMap contributors", fr: "Carte : contributeurs OpenStreetMap" },
  "limits.too_many_api": { en: "Too many requests. The API allows 60 requests a minute per address; bulk users should use the downloads.", fr: "Trop de requêtes. L'API permet 60 requêtes par minute et par adresse; pour un usage en masse, utilisez les téléchargements." },
  "limits.too_many": { en: "Too many requests from this address. Try again in a minute.", fr: "Trop de requêtes depuis cette adresse. Réessayez dans une minute." },
  // --- measurement, citation and bluesky ---
  "data.views_note": {
    en: "The site counts the pages it serves in aggregate, on its own server: for each response it keeps the kind of page, the language, the country reported by Cloudflare's network, the name of the referring website and the response status. When a feed reader fetches a feed and states how many people it fetches it for, that number is kept as well. It sets no cookie for this, runs no tracking script in the browser, and keeps no IP address or other personal data.",
    fr: "Le site compte de façon agrégée les pages qu'il sert, sur son propre serveur : pour chaque réponse, il conserve le type de page, la langue, le pays indiqué par le réseau de Cloudflare, le nom du site d'où vient le visiteur et le statut de la réponse. Lorsqu'un lecteur de fils télécharge un fil et indique pour combien de personnes il le fait, ce nombre est aussi conservé. Il ne dépose aucun témoin à cette fin, n'exécute aucun script de suivi dans le navigateur et ne conserve aucune adresse IP ni autre donnée personnelle.",
  },
  "cite.title": { en: "How to Cite", fr: "Comment citer" },
  "cite.text": {
    en: "Each new ESDC quarter is deposited on Zenodo, with a DOI, as a version of the files derived from ESDC's lists alone (approved_quarterly.csv, refused_quarterly.csv and esdc_resources.csv). Cite the version you used:",
    fr: "Chaque nouveau trimestre d'EDSC est déposé sur Zenodo, avec un DOI, comme version des fichiers tirés des seules listes d'EDSC (approved_quarterly.csv, refused_quarterly.csv et esdc_resources.csv). Citez la version utilisée :",
  },
  "cite.reference": {
    en: "{author} ({year}). {title} (Version {version}) [Data set]. Zenodo. {doi}",
    fr: "{author} ({year}). {title} (version {version}) [Jeu de données]. Zenodo. {doi}",
  },
  "cite.concept": {
    en: "To cite every version at once, or to point at whichever version is newest, use the concept DOI {doi}.",
    fr: "Pour citer toutes les versions à la fois, ou pour renvoyer à la plus récente, utilisez le DOI de concept {doi}.",
  },
  "support.bluesky_free": {
    en: "The same daily post on Bluesky is free to send, so it carries a link to the site.",
    fr: "La même publication quotidienne sur Bluesky est gratuite, et elle comporte donc un lien vers le site.",
  },
  // --- feeds and watchlist ---
  "feeds.title": { en: "Atom Feeds", fr: "Fils Atom" },
  "feeds.description": {
    en: "Atom feeds of new LMIA records for Canada and by province, stream, occupation group and metropolitan area. For feed readers, Slack and Teams. No sign-up.",
    fr: "Fils Atom des nouveaux dossiers EIMT, pour le Canada et par province, volet, groupe de professions et région métropolitaine. Sans inscription.",
  },
  "feeds.lead": {
    en: "Each feed lists the newest 50 records of one kind, for Canada or for one province, stream, occupation group or metropolitan area. Entries are in English and French, link to the employer's profile and name their source. The feeds are rebuilt with the data every night.",
    fr: "Chaque fil présente les 50 dossiers les plus récents d'un type, pour le Canada ou pour une province, un volet, un groupe de professions ou une région métropolitaine. Les entrées sont en anglais et en français, renvoient au profil de l'employeur et nomment leur source. Les fils sont reconstruits avec les données chaque nuit.",
  },
  "feeds.privacy": {
    en: "A feed is a plain file that your feed reader fetches. LMIA Watch counts these fetches and keeps the number of subscribers a reader states, but stores no reader address, name or list of subscribers, and cannot tell who reads a feed.",
    fr: "Un fil est un simple fichier que votre lecteur de fils télécharge. LMIA Watch compte ces téléchargements et garde le nombre d'abonnés qu'un lecteur indique, mais ne conserve aucune adresse, aucun nom ni aucune liste d'abonnés, et ne peut savoir qui lit un fil.",
  },
  "feeds.records_note": {
    en: "Feeds carry records only, never indicators, and nothing the employer profiles do not already show. IRCC findings appear as IRCC published them.",
    fr: "Les fils ne contiennent que des dossiers, jamais d'indicateurs, et rien que les profils d'employeurs n'affichent déjà. Les constats d'IRCC paraissent tels qu'IRCC les a publiés.",
  },
  "feeds.toc_kinds": { en: "What Each Feed Holds", fr: "Contenu de chaque fil" },
  "feeds.toc_canada": { en: "National Feeds", fr: "Fils nationaux" },
  "feeds.toc_prov": { en: "By Province or Territory", fr: "Par province ou territoire" },
  "feeds.toc_stream": { en: "By ESDC Stream", fr: "Par volet d'EDSC" },
  "feeds.toc_noc": { en: "By Occupation Group", fr: "Par groupe de professions" },
  "feeds.toc_cma": { en: "By Metropolitan Area", fr: "Par région métropolitaine" },
  "feeds.toc_subscribe": { en: "How to Subscribe", fr: "Comment s'abonner" },
  "feeds.ev.pending": { en: "New pending postings", fr: "Nouvelles offres en attente" },
  "feeds.ev.approved": { en: "New Approved LMIA flags", fr: "Nouvelles mentions « EIMT approuvée »" },
  "feeds.ev.findings": { en: "New IRCC findings", fr: "Nouveaux constats d'IRCC" },
  "feeds.ev.quarters": { en: "ESDC quarterly lists", fr: "Listes trimestrielles d'EDSC" },
  "feeds.about.pending": {
    en: "Job Bank postings first seen with the \"LMIA requested\" flag, newest first.",
    fr: "Offres du Guichet-Emplois vues pour la première fois avec la mention « EIMT demandée », les plus récentes en premier.",
  },
  "feeds.about.approved": {
    en: "Job Bank postings first seen with the \"Approved LMIA\" flag, newest first.",
    fr: "Offres du Guichet-Emplois vues pour la première fois avec la mention « EIMT approuvée », les plus récentes en premier.",
  },
  "feeds.about.findings": {
    en: "Rows of IRCC's list of employers found non-compliant, newest first by the date LMIA Watch first recorded them.",
    fr: "Lignes de la liste d'IRCC des employeurs jugés non conformes, les plus récentes en premier selon la date où LMIA Watch les a relevées.",
  },
  "feeds.about.quarters": {
    en: "One entry per ESDC quarterly release, with the approved and refused records it holds for the feed's area or group.",
    fr: "Une entrée par publication trimestrielle d'EDSC, avec les dossiers approuvés et refusés qu'elle contient pour la région ou le groupe du fil.",
  },
  "feeds.col_feed": { en: "Feed", fr: "Fil" },
  "feeds.col_holds": { en: "What it holds", fr: "Contenu" },
  "feeds.col_address": { en: "Address", fr: "Adresse" },
  "feeds.col_prov": { en: "Province or territory", fr: "Province ou territoire" },
  "feeds.col_noc": { en: "Occupation group (NOC 2021)", fr: "Groupe de professions (CNP 2021)" },
  "feeds.col_cma": { en: "Metropolitan area", fr: "Région métropolitaine" },
  "feeds.pattern": { en: "Addresses follow the pattern {pattern}.", fr: "Les adresses suivent le modèle {pattern}." },
  "feeds.stream_note": {
    en: "Only the quarterly lists carry a stream, so these feeds hold releases only.",
    fr: "Seules les listes trimestrielles indiquent un volet; ces fils ne contiennent donc que des publications.",
  },
  "feeds.noc_note": {
    en: "Grouped by the first two digits of the NOC 2021 code: the broad category and the TEER level. Postings count when their page gave an occupation code; list rows count from 2024 Q2, when ESDC moved to NOC 2021.",
    fr: "Regroupement selon les deux premiers chiffres du code CNP 2021 : la grande catégorie et le niveau FEER. Les offres comptent quand leur page indique un code de profession; les inscriptions comptent depuis le T2 2024, quand EDSC est passé à la CNP 2021.",
  },
  "feeds.cma_note": {
    en: "A record is placed in a census metropolitan area by the forward sortation area of its postal code (Statistics Canada 2021 boundaries).",
    fr: "Un dossier est situé dans une région métropolitaine de recensement selon la région de tri d'acheminement de son code postal (limites de 2021 de Statistique Canada).",
  },
  "feeds.fresh_note": {
    en: "A province, stream, group or area feed is listed while it holds a record from the last {days} days ({qdays} days for the quarterly lists, which come three to four months apart). The national feeds are always there.",
    fr: "Un fil de province, de volet, de groupe ou de région est offert tant qu'il contient un dossier des {days} derniers jours ({qdays} jours pour les listes trimestrielles, publiées à trois ou quatre mois d'intervalle). Les fils nationaux sont toujours offerts.",
  },
  "feeds.none_yet": {
    en: "The province, stream, occupation and area feeds are listed after the next nightly update.",
    fr: "Les fils par province, volet, profession et région seront offerts après la prochaine mise à jour de nuit.",
  },
  "feeds.none_scope": { en: "No feed of this kind holds a recent record.", fr: "Aucun fil de ce type ne contient de dossier récent." },
  "feeds.cell_aria": { en: "{scope}: {event}", fr: "{scope} : {event}" },
  "feeds.sub_reader": {
    en: "Feed reader: add the feed's address as a new subscription. Any reader that takes RSS or Atom works.",
    fr: "Lecteur de fils : ajoutez l'adresse du fil comme nouvel abonnement. Tout lecteur qui accepte RSS ou Atom convient.",
  },
  "feeds.sub_slack": {
    en: "Slack: in a channel, type {command} followed by the feed's address. The workspace needs Slack's RSS app.",
    fr: "Slack : dans un canal, tapez {command} suivi de l'adresse du fil. L'espace de travail doit avoir l'application RSS de Slack.",
  },
  "feeds.sub_teams": {
    en: "Microsoft Teams: in a channel, add a workflow that posts new items from an RSS feed, and give it the feed's address.",
    fr: "Microsoft Teams : dans un canal, ajoutez un flux de travail qui publie les nouveaux éléments d'un fil RSS, et donnez-lui l'adresse du fil.",
  },
  "feeds.sub_email": {
    en: "Email: a feed-to-email service can send new entries to your inbox. That service, not LMIA Watch, holds your address.",
    fr: "Courriel : un service qui transforme un fil en courriels peut envoyer les nouvelles entrées dans votre boîte de réception. Ce service, et non LMIA Watch, conserve votre adresse.",
  },
  "feeds.watch_note": { en: "To follow one employer, use the {watchlist}.", fr: "Pour suivre un seul employeur, utilisez la {watchlist}." },
  "feeds.watch_link": { en: "watchlist", fr: "liste de suivi" },
  "feeds.link_title": { en: "LMIA Watch: {event}, Canada", fr: "LMIA Watch : {event}, Canada" },
  "feeds.noc_group": { en: "{code}: {category}, TEER {teer}", fr: "{code} : {category}, FEER {teer}" },
  "feeds.noc_cat.0": { en: "legislative and senior management occupations", fr: "membres des corps législatifs et cadres supérieurs" },
  "feeds.noc_cat.1": { en: "business, finance and administration", fr: "affaires, finance et administration" },
  "feeds.noc_cat.2": { en: "natural and applied sciences", fr: "sciences naturelles et appliquées" },
  "feeds.noc_cat.3": { en: "health", fr: "santé" },
  "feeds.noc_cat.4": { en: "education, law and social, community and government services", fr: "enseignement, droit et services sociaux, communautaires et gouvernementaux" },
  "feeds.noc_cat.5": { en: "art, culture, recreation and sport", fr: "arts, culture, sports et loisirs" },
  "feeds.noc_cat.6": { en: "sales and service", fr: "vente et services" },
  "feeds.noc_cat.7": { en: "trades, transport and equipment operators", fr: "métiers, transport, machinerie et domaines apparentés" },
  "feeds.noc_cat.8": { en: "natural resources, agriculture and related production", fr: "ressources naturelles, agriculture et production connexe" },
  "feeds.noc_cat.9": { en: "manufacturing and utilities", fr: "fabrication et services d'utilité publique" },
  "watch.title": { en: "Watchlist", fr: "Liste de suivi" },
  "watch.description": {
    en: "Follow employers' LMIA records from this browser and see what changed since your last visit. The list stays in your browser; LMIA Watch stores nothing.",
    fr: "Suivez les dossiers EIMT d'employeurs dans ce navigateur et voyez ce qui a changé depuis votre dernière visite. La liste reste dans votre navigateur.",
  },
  "watch.lead": {
    en: "Press Watch on an employer's profile and the employer appears here, with its status, its counts and what changed since your last visit.",
    fr: "Appuyez sur Suivre dans le profil d'un employeur et l'employeur paraît ici, avec son statut, ses chiffres et ce qui a changé depuis votre dernière visite.",
  },
  "watch.privacy": {
    en: "The list is kept in this browser's storage only. LMIA Watch stores nothing about it and cannot see it. It does not follow you to another browser or device, and a private window forgets it when closed; the code at the bottom of this page moves it.",
    fr: "La liste est conservée dans le stockage de ce navigateur seulement. LMIA Watch n'en conserve rien et ne peut pas la voir. Elle ne vous suit pas dans un autre navigateur ou appareil, et une fenêtre privée l'oublie à sa fermeture; le code au bas de cette page permet de la déplacer.",
  },
  "watch.records_note": {
    en: "Each row shows only what the employer's profile shows, read from the same published files.",
    fr: "Chaque ligne n'affiche que ce que montre le profil de l'employeur, lu dans les mêmes fichiers publiés.",
  },
  "watch.empty": {
    en: "No employer is on the watchlist in this browser yet. Find one in the {search} and press Watch on its profile.",
    fr: "Aucun employeur n'est encore dans la liste de suivi de ce navigateur. Trouvez-en un dans la {search} et appuyez sur Suivre dans son profil.",
  },
  "watch.search_link": { en: "search", fr: "recherche" },
  "watch.noscript": {
    en: "The watchlist is read from this browser's storage, which needs JavaScript.",
    fr: "La liste de suivi est lue dans le stockage de ce navigateur, ce qui exige JavaScript.",
  },
  "watch.no_storage": {
    en: "This browser does not let the site keep a list (a private window or blocked site storage), so the watchlist cannot work here.",
    fr: "Ce navigateur ne permet pas au site de conserver une liste (fenêtre privée ou stockage bloqué); la liste de suivi ne peut donc pas fonctionner ici.",
  },
  "watch.watch": { en: "Watch", fr: "Suivre" },
  "watch.watching": { en: "Watching", fr: "Suivi en cours" },
  "watch.full": { en: "Watchlist full ({max})", fr: "Liste de suivi pleine ({max})" },
  "watch.button_title": {
    en: "Keep this employer on the watchlist in this browser",
    fr: "Garder cet employeur dans la liste de suivi de ce navigateur",
  },
  "watch.col_latest": { en: "Latest record", fr: "Dernier dossier" },
  "watch.col_new": { en: "Since your last visit", fr: "Depuis votre dernière visite" },
  "watch.col_manage": { en: "Manage", fr: "Gérer" },
  "watch.remove": { en: "Remove", fr: "Retirer" },
  "watch.remove_aria": { en: "Remove {name} from the watchlist", fr: "Retirer {name} de la liste de suivi" },
  "watch.loading": { en: "Loading {n} watched employers.", fr: "Chargement de {n} employeurs suivis." },
  "watch.count_one": { en: "{n} employer watched in this browser.", fr: "{n} employeur suivi dans ce navigateur." },
  "watch.count_many": { en: "{n} employers watched in this browser.", fr: "{n} employeurs suivis dans ce navigateur." },
  "watch.last_visit": { en: "Changes are counted from your last visit, {date}.", fr: "Les changements sont comptés depuis votre dernière visite, le {date}." },
  "watch.first_visit": { en: "Changes will be marked from your next visit.", fr: "Les changements seront signalés à partir de votre prochaine visite." },
  "watch.nothing_new": { en: "Nothing new", fr: "Rien de nouveau" },
  "watch.added_since": { en: "Added since your last visit", fr: "Ajouté depuis votre dernière visite" },
  "watch.new_postings_one": { en: "{n} new Job Bank posting", fr: "{n} nouvelle offre du Guichet-Emplois" },
  "watch.new_postings_many": { en: "{n} new Job Bank postings", fr: "{n} nouvelles offres du Guichet-Emplois" },
  "watch.new_approved_one": { en: "{n} new Approved LMIA flag", fr: "{n} nouvelle mention « EIMT approuvée »" },
  "watch.new_approved_many": { en: "{n} new Approved LMIA flags", fr: "{n} nouvelles mentions « EIMT approuvée »" },
  "watch.new_positive_one": { en: "{n} new approved list record", fr: "{n} nouvelle inscription sur la liste positive" },
  "watch.new_positive_many": { en: "{n} new approved list records", fr: "{n} nouvelles inscriptions sur la liste positive" },
  "watch.new_negative_one": { en: "{n} new refused list record", fr: "{n} nouvelle inscription sur la liste négative" },
  "watch.new_negative_many": { en: "{n} new refused list records", fr: "{n} nouvelles inscriptions sur la liste négative" },
  "watch.new_findings_one": { en: "{n} new IRCC finding", fr: "{n} nouveau constat d'IRCC" },
  "watch.new_findings_many": { en: "{n} new IRCC findings", fr: "{n} nouveaux constats d'IRCC" },
  "watch.status_was": { en: "Status was {status}", fr: "Statut précédent : {status}" },
  "watch.missing": { en: "No profile under {id} in the latest data.", fr: "Aucun profil sous {id} dans les dernières données." },
  "watch.load_failed": { en: "This profile could not be loaded. Try again later.", fr: "Ce profil n'a pas pu être chargé. Réessayez plus tard." },
  "watch.move_h": { en: "Move the List to Another Browser", fr: "Déplacer la liste vers un autre navigateur" },
  "watch.move_text": {
    en: "The code holds only the employer IDs. Show it here, copy it, then paste it into this page in the other browser. A list of profile links or employer IDs works too.",
    fr: "Le code ne contient que les identifiants des employeurs. Affichez-le ici, copiez-le, puis collez-le dans cette page dans l'autre navigateur. Une liste de liens de profil ou d'identifiants d'employeur fonctionne aussi.",
  },
  "watch.export": { en: "Show the code", fr: "Afficher le code" },
  "watch.export_label": { en: "Code for this list", fr: "Code de cette liste" },
  "watch.export_empty": { en: "The list is empty, so there is no code to show.", fr: "La liste est vide; il n'y a donc aucun code à afficher." },
  "watch.import_label": { en: "Paste a code, profile links or employer IDs", fr: "Collez un code, des liens de profil ou des identifiants d'employeur" },
  "watch.import": { en: "Add to the list", fr: "Ajouter à la liste" },
  "watch.import_one": { en: "{n} employer added.", fr: "{n} employeur ajouté." },
  "watch.import_many": { en: "{n} employers added.", fr: "{n} employeurs ajoutés." },
  "watch.import_known": { en: "Those employers are already on the list.", fr: "Ces employeurs sont déjà dans la liste." },
  "watch.import_none": { en: "No employer ID was found in that text.", fr: "Aucun identifiant d'employeur n'a été trouvé dans ce texte." },
  "watch.import_full": { en: "The list holds at most {max} employers; the others were not added.", fr: "La liste contient au plus {max} employeurs; les autres n'ont pas été ajoutés." },
  "watch.limit_note": {
    en: "The list holds up to {max} employers. The page reads each one's profile file (about 120 KB) straight from the published data.",
    fr: "La liste contient au plus {max} employeurs. La page lit le fichier de profil de chacun (environ 120 ko) directement dans les données publiées.",
  },

  // --- releases and rankings ---
  "rel.caveat_title": { en: "Reading These Tables", fr: "Comment lire ces tableaux" },
  "rel.caveat_positions": {
    en: "Positions on approved LMIAs are not workers who arrived. ESDC counts the positions an LMIA allows an employer to fill. It does not count work permits issued or workers who came, and an employer may cancel positions after approval.",
    fr: "Les postes visés par des EIMT approuvées ne sont pas des travailleurs arrivés. EDSC compte les postes qu'une EIMT permet à l'employeur de pourvoir. Il ne compte ni les permis de travail délivrés ni les travailleurs venus, et un employeur peut annuler des postes après l'approbation.",
  },
  "rel.caveat_leaders": {
    en: "Large farms, packers and health authorities lead these tables by design: they hire many workers at a time and apply every season. A place in a table reports a count of approved positions and is not a finding about the employer.",
    fr: "Les grandes exploitations agricoles, les emballeurs et les autorités sanitaires arrivent en tête de ces tableaux par conception : ils embauchent beaucoup de travailleurs à la fois et présentent des demandes chaque saison. Le rang dans un tableau rend compte d'un nombre de postes approuvés et ne constitue pas un constat au sujet de l'employeur.",
  },
  "rel.index_title": { en: "Quarterly Releases", fr: "Publications trimestrielles" },
  "rel.crumb": { en: "Quarterly releases", fr: "Publications trimestrielles" },
  "rel.index_lead": {
    en: "ESDC publishes its lists of employers issued a positive or negative LMIA once a quarter, three to four months after the quarter ends. Each release has a page with its totals, the largest approvals, employers new to the positive list, the largest changes from the previous release, refusals by province and stream, and the source files.",
    fr: "EDSC publie ses listes des employeurs ayant reçu une EIMT positive ou négative une fois par trimestre, trois à quatre mois après la fin du trimestre. Chaque publication a sa page : totaux, approbations les plus importantes, employeurs nouveaux sur la liste positive, plus fortes variations depuis la publication précédente, refus par province et par volet, et fichiers sources.",
  },
  "rel.index_early": {
    en: "Before 2017 Q3, ESDC published one file a year (the 2014 file covers June 20 to December 31) and one file for 2017 Q1 and Q2.",
    fr: "Avant le T3 2017, EDSC publiait un fichier par année (celui de 2014 couvre du 20 juin au 31 décembre) et un fichier pour les T1 et T2 2017.",
  },
  "rel.rankings_link": {
    en: "Rankings by year: provinces, streams, occupations and employers",
    fr: "Classements par année : provinces, volets, professions et employeurs",
  },
  "rel.col_release": { en: "Release", fr: "Publication" },
  "rel.col_published": { en: "Published", fr: "Date de publication" },
  "rel.col_positive_rows": { en: "Approved rows", fr: "Inscriptions approuvées" },
  "rel.col_negative_rows": { en: "Refused rows", fr: "Inscriptions refusées" },
  "rel.col_employers": { en: "Employers", fr: "Employeurs" },
  "rel.col_rows": { en: "Rows", fr: "Inscriptions" },
  "rel.col_province": { en: "Province or territory", fr: "Province ou territoire" },
  "rel.col_requested": { en: "Positions requested", fr: "Postes demandés" },
  "rel.col_this": { en: "This release", fr: "Cette publication" },
  "rel.col_prev": { en: "Previous ({period})", fr: "Précédente ({period})" },
  "rel.col_before": { en: "Previous release", fr: "Publication précédente" },
  "rel.col_change": { en: "Change", fr: "Variation" },
  "rel.col_file": { en: "File", fr: "Fichier" },
  "rel.col_download": { en: "Download", fr: "Téléchargement" },
  "rel.col_checksum": { en: "Checksum (SHA-256)", fr: "Somme de contrôle (SHA-256)" },
  "rel.h1": { en: "LMIA Employer Lists, {period}", fr: "Listes des employeurs EIMT, {period}" },
  "rel.lead": {
    en: "ESDC's lists of employers issued a positive or negative LMIA in {period}, published {date}.",
    fr: "Listes d'EDSC des employeurs ayant reçu une EIMT positive ou négative, {period}, publiées le {date}.",
  },
  "rel.lead_undated": {
    en: "ESDC's lists of employers issued a positive or negative LMIA in {period}.",
    fr: "Listes d'EDSC des employeurs ayant reçu une EIMT positive ou négative, {period}.",
  },
  "rel.span_2014": {
    en: "The 2014 lists cover LMIAs issued from June 20 to December 31, 2014.",
    fr: "Les listes de 2014 couvrent les EIMT délivrées du 20 juin au 31 décembre 2014.",
  },
  "rel.span_many": {
    en: "This release covers {n} quarters, so its totals are larger than a single quarter's.",
    fr: "Cette publication couvre {n} trimestres : ses totaux dépassent donc ceux d'un seul trimestre.",
  },
  "rel.prev_link": { en: "Previous release: {period}", fr: "Publication précédente : {period}" },
  "rel.next_link": { en: "Next release: {period}", fr: "Publication suivante : {period}" },
  "rel.all_link": { en: "All releases", fr: "Toutes les publications" },
  "rel.totals": { en: "Totals", fr: "Totaux" },
  "rel.row_positive_rows": { en: "Rows on the positive list", fr: "Inscriptions sur la liste positive" },
  "rel.row_positions": { en: "Positions approved", fr: "Postes approuvés" },
  "rel.row_lmias": { en: "LMIAs approved", fr: "EIMT approuvées" },
  "rel.row_employers": { en: "Employers with an approval", fr: "Employeurs ayant une approbation" },
  "rel.row_negative_rows": { en: "Rows on the negative list", fr: "Inscriptions sur la liste négative" },
  "rel.row_negative_positions": { en: "Positions requested on refused LMIAs", fr: "Postes demandés dans les EIMT refusées" },
  "rel.row_negative_employers": { en: "Employers with a refusal", fr: "Employeurs ayant un refus" },
  "rel.span_differs": {
    en: "The previous release covers {prev} quarters and this one {n}, so the change compares unequal spans.",
    fr: "La publication précédente couvre {prev} trimestres et celle-ci {n} : la variation compare donc des durées inégales.",
  },
  "rel.top": { en: "Largest Approvals", fr: "Approbations les plus importantes" },
  "rel.top_note": {
    en: "Employers by positions approved in this release, every row added together.",
    fr: "Employeurs selon les postes approuvés dans cette publication, toutes inscriptions additionnées.",
  },
  "rel.new": { en: "New to the Positive List", fr: "Nouveaux sur la liste positive" },
  "rel.new_text": {
    en: "{n} employers appear on the positive list for the first time, with {positions} positions.",
    fr: "{n} employeurs figurent sur la liste positive pour la première fois, avec {positions} postes.",
  },
  "rel.new_note": {
    en: "An employer counts as new when no earlier positive list carries its legal name in the same province, so a renamed or relocated employer reads as new.",
    fr: "Un employeur est compté comme nouveau quand aucune liste positive antérieure ne porte sa dénomination sociale dans la même province : un employeur qui a changé de nom ou de province paraît donc nouveau.",
  },
  "rel.new_first": {
    en: "This is the first list on record, so every employer on it is new.",
    fr: "Il s'agit de la première liste disponible : tous les employeurs qui y figurent sont nouveaux.",
  },
  "rel.changes": { en: "Largest Changes from {period}", fr: "Plus fortes variations par rapport à la publication {period}" },
  "rel.changes_note": {
    en: "Positions approved in this release minus positions approved in the previous one, by employer. Farm approvals follow the growing season, so many changes reflect timing.",
    fr: "Postes approuvés dans cette publication moins ceux de la précédente, par employeur. Les approbations agricoles suivent la saison de culture : bien des variations tiennent donc au calendrier.",
  },
  "rel.increases": { en: "Increases", fr: "Hausses" },
  "rel.decreases": { en: "Decreases", fr: "Baisses" },
  "rel.none": { en: "None.", fr: "Aucune." },
  "rel.approvals_by": { en: "Approvals by Province and Stream", fr: "Approbations par province et par volet" },
  "rel.refusals_by": { en: "Refusals by Province and Stream", fr: "Refus par province et par volet" },
  "rel.refusals_note": {
    en: "Rows from the {source}, which the {methodology} counts as Refused. Each row is one application ESDC refused; a refusal is a decision on that application, not a finding against the employer.",
    fr: "Inscriptions de la {source}, que la {methodology} compte comme refusées. Chaque inscription est une demande qu'EDSC a refusée; un refus est une décision sur cette demande et non un constat contre l'employeur.",
  },
  "rel.negative_list": { en: "ESDC negative LMIA employers list", fr: "liste des employeurs ayant reçu une EIMT négative d'EDSC" },
  "rel.methodology_link": { en: "Methodology page", fr: "page Méthodologie" },
  "rel.not_recorded": { en: "Not recorded", fr: "Non précisé" },
  "rel.stream_other": { en: "Other or unspecified", fr: "Autre ou non précisé" },
  "rel.stream_missing": {
    en: "Most rows in this file carry no stream, so no breakdown by stream is shown.",
    fr: "La plupart des inscriptions de ce fichier ne précisent pas de volet : aucune répartition par volet n'est donc présentée.",
  },
  "rel.sources": { en: "Source Files", fr: "Fichiers sources" },
  "rel.sources_note": {
    en: "Each file as ESDC published it on the Open Government Portal, and the copy kept in this site's mirror. The {sums} file lists every copy's checksum.",
    fr: "Chaque fichier tel qu'EDSC l'a publié sur le Portail du gouvernement ouvert, et la copie conservée dans le miroir de ce site. Le fichier {sums} donne la somme de contrôle de chaque copie.",
  },
  "rel.list.positive": { en: "Positive (approved)", fr: "Positive (approuvées)" },
  "rel.list.negative": { en: "Negative (refused)", fr: "Négative (refusées)" },
  "rel.esdc_file": { en: "ESDC file", fr: "fichier d'EDSC" },
  "rel.mirror_copy": { en: "mirror copy", fr: "copie miroir" },
  "rel.not_found": { en: "Release Not Found", fr: "Publication introuvable" },
  "rel.not_found_text": {
    en: "No ESDC release is published under that name. The {all} names every release on record.",
    fr: "Aucune publication d'EDSC ne porte ce nom. La {all} les énumère toutes.",
  },
  "rel.not_found_link": { en: "list of releases", fr: "liste des publications" },
  "rel.home_link": {
    en: "Every quarterly release, with its largest approvals",
    fr: "Toutes les publications trimestrielles et leurs approbations les plus importantes",
  },
  "rel.data_link": {
    en: "Each release also has a page with its totals and largest approvals: {link}.",
    fr: "Chaque publication a aussi une page avec ses totaux et ses approbations les plus importantes : {link}.",
  },
  "rel.seo_index_desc": {
    en: "Every quarterly ESDC list of employers issued a positive or negative LMIA since {start}, with totals, the largest approvals and the source files.",
    fr: "Chaque liste trimestrielle d'EDSC des employeurs ayant reçu une EIMT positive ou négative depuis {start} : totaux, approbations et fichiers sources.",
  },
  "rel.seo_title": { en: "LMIA Approvals and Refusals, {period}", fr: "EIMT approuvées et refusées, {period}" },
  "rel.seo_desc": {
    en: "ESDC's {period} LMIA employer lists: {rows} approved rows for {positions} positions and {refused} refused rows, with the largest approvals and source files.",
    fr: "Listes EIMT d'EDSC, {period} : {rows} inscriptions approuvées pour {positions} postes et {refused} refusées, avec les fichiers sources.",
  },
  "rel.seo_desc_short": {
    en: "ESDC's {period} LMIA employer lists: {rows} approved rows for {positions} positions and {refused} refused rows.",
    fr: "Listes EIMT d'EDSC, {period} : {rows} inscriptions approuvées ({positions} postes) et {refused} refusées.",
  },
  "rank.title": { en: "Rankings", fr: "Classements" },
  "rank.h1_all": { en: "Rankings: All Years", fr: "Classements : toutes les années" },
  "rank.h1_year": { en: "Rankings: {year}", fr: "Classements : {year}" },
  "rank.lead": {
    en: "Positions approved on ESDC's positive LMIA lists, ranked by province, stream, occupation and employer.",
    fr: "Postes approuvés sur les listes positives d'EDSC, classés par province, volet, profession et employeur.",
  },
  "rank.years_label": { en: "Year", fr: "Année" },
  "rank.all_years": { en: "All years", fr: "Toutes les années" },
  "rank.covers_list": { en: "Releases included: {periods}.", fr: "Publications comprises : {periods}." },
  "rank.covers_range": { en: "{n} releases, {first} to {last}.", fr: "{n} publications, de {first} à {last}." },
  "rank.partial": {
    en: "The latest release is {period}, so {year} is not complete.",
    fr: "La publication la plus récente est {period} : l'année {year} n'est donc pas complète.",
  },
  "rank.totals": {
    en: "{positions} positions approved on {rows} rows, {employers} employers.",
    fr: "{positions} postes approuvés, {rows} inscriptions, {employers} employeurs.",
  },
  "rank.by_province": { en: "Positions Approved by Province", fr: "Postes approuvés par province" },
  "rank.by_stream": { en: "Positions Approved by Stream", fr: "Postes approuvés par volet" },
  "rank.stream_years": {
    en: "Years included: {years}. Years in which most rows carry no stream are left out: the 2014 to 2016 files have no stream column.",
    fr: "Années comprises : {years}. Les années où la plupart des inscriptions ne précisent pas de volet sont exclues : les fichiers de 2014 à 2016 n'ont pas de colonne de volet.",
  },
  "rank.stream_missing": {
    en: "Most rows from {year} carry no stream, so no ranking by stream is shown for this year.",
    fr: "La plupart des inscriptions de {year} ne précisent pas de volet : aucun classement par volet n'est donc présenté pour cette année.",
  },
  "rank.by_occupation": { en: "Positions Approved by Occupation", fr: "Postes approuvés par profession" },
  "rank.noc_note": {
    en: "ESDC moved from the 2011 National Occupational Classification (four-digit codes) to NOC 2021 (five-digit codes) with the 2024 Q2 lists. NOC 2021 split, merged and renumbered many occupations, so the two do not match code for code. Each is ranked on its own, and no figure adds the two together.",
    fr: "EDSC est passé de la Classification nationale des professions 2011 (codes à quatre chiffres) à la CNP 2021 (codes à cinq chiffres) avec les listes du T2 2024. La CNP 2021 a scindé, fusionné et renuméroté de nombreuses professions : les deux ne se correspondent donc pas code pour code. Chacune est classée séparément, et aucun chiffre n'additionne les deux.",
  },
  "rank.noc_era": { en: "NOC {era}, {first} to {last}", fr: "CNP {era}, {first} à {last}" },
  "rank.noc_era_one": { en: "NOC {era}, {period}", fr: "CNP {era}, {period}" },
  "rank.noc_era_total": {
    en: "{positions} positions across {codes} occupation codes; the first {n} are shown.",
    fr: "{positions} postes répartis entre {codes} codes de profession; les {n} premiers sont présentés.",
  },
  "rank.no_occupation": {
    en: "The {periods} lists name no occupation, so their rows are not in the occupation tables.",
    fr: "Les listes de {periods} ne précisent aucune profession : leurs inscriptions ne figurent donc pas dans les tableaux par profession.",
  },
  "rank.by_employer": { en: "Employers by Positions Approved", fr: "Employeurs selon les postes approuvés" },
  "rank.employer_note": {
    en: "Positions added over every row in the period, by employer. Employers are merged by legal name and province.",
    fr: "Postes additionnés sur toutes les inscriptions de la période, par employeur. Les employeurs sont fusionnés selon la dénomination sociale et la province.",
  },
  "rank.col_rank": { en: "Rank", fr: "Rang" },
  "rank.col_share": { en: "Share", fr: "Part" },
  "rank.col_code": { en: "NOC code", fr: "Code CNP" },
  "rank.col_occupation": { en: "Occupation", fr: "Profession" },
  "rank.percent": { en: "{n}%", fr: "{n} %" },
  "rank.percent_small": { en: "<0.1%", fr: "< 0,1 %" },
  "rank.and": { en: "and", fr: "et" },
  "rank.not_found": { en: "No Rankings for That Year", fr: "Aucun classement pour cette année" },
  "rank.not_found_text": {
    en: "No ESDC list is on record for that year. Pick a year on the {rankings}.",
    fr: "Aucune liste d'EDSC n'est disponible pour cette année. Choisissez une année sur la {rankings}.",
  },
  "rank.page_link": { en: "rankings page", fr: "page des classements" },
  "rank.seo_title_all": {
    en: "LMIA Rankings by Province, Stream, Occupation and Employer",
    fr: "Classements EIMT par province, volet, profession et employeur",
  },
  "rank.seo_title_year": { en: "LMIA Rankings, {year}", fr: "Classements EIMT, {year}" },
  "rank.seo_desc_all": {
    en: "Approved LMIA positions ranked by province, stream, occupation and employer for each year since {start} and all years together, from ESDC's lists.",
    fr: "Postes EIMT approuvés classés par province, volet, profession et employeur, pour chaque année depuis {start} et toutes années confondues.",
  },
  "rank.seo_desc_year": {
    en: "Approved LMIA positions in {year} ranked by province, stream, occupation and employer, from ESDC's quarterly positive lists.",
    fr: "Postes EIMT approuvés en {year}, classés par province, volet, profession et employeur, selon les listes positives d'EDSC.",
  },
  // --- occupations and places ---
  "places.index_title": { en: "LMIA Records by Place", fr: "Dossiers EIMT par lieu" },
  "places.index_seo_title": { en: "LMIA Records by Province, Metro Area and City", fr: "Dossiers EIMT par province, région métropolitaine et ville" },
  "places.index_description": {
    en: "LMIA approvals, refusals and pending Job Bank postings by province, census metropolitan area and city, with quarterly trends and wages by occupation.",
    fr: "EIMT approuvées et refusées et offres en attente au Guichet-Emplois par province, région métropolitaine et ville, avec tendances et salaires par profession.",
  },
  "places.index_lead": {
    en: "Provinces, census metropolitan areas and every city with {threshold} records or more, from ESDC's lists since 2014 and Job Bank postings.",
    fr: "Provinces, régions métropolitaines de recensement et chaque ville comptant {threshold} dossiers ou plus, d'après les listes d'EDSC depuis 2014 et les offres du Guichet-Emplois.",
  },
  "places.to_occupations": { en: "Browse by occupation instead", fr: "Parcourir plutôt par profession" },
  "places.not_published": { en: "These pages have not been published yet.", fr: "Ces pages ne sont pas encore publiées." },
  "places.provinces": { en: "Provinces and Territories", fr: "Provinces et territoires" },
  "places.cmas": { en: "Census Metropolitan Areas", fr: "Régions métropolitaines de recensement" },
  "places.cmas_note": {
    en: "A census metropolitan area takes in every record whose postal area lies inside it, suburbs included. The number is its record count.",
    fr: "Une région métropolitaine de recensement regroupe tous les dossiers dont le secteur postal s'y trouve, banlieue comprise. Le nombre est son total de dossiers.",
  },
  "places.cities": { en: "Cities", fr: "Villes" },
  "places.cities_note": {
    en: "Cities as written on the records, with {threshold} records or more. The number is the record count.",
    fr: "Villes telles qu'inscrites aux dossiers, comptant {threshold} dossiers ou plus. Le nombre est le total de dossiers.",
  },
  "places.all_cities": { en: "All {n} city pages in {province}", fr: "Les {n} pages de villes : {province}" },
  "places.not_found": { en: "Place Not Found", fr: "Lieu introuvable" },
  "places.back_index": { en: "See every place", fr: "Voir tous les lieux" },
  "places.cma_heading": { en: "{name} (census metropolitan area)", fr: "{name} (région métropolitaine de recensement)" },
  "places.seo_title": { en: "LMIA Records in {place}", fr: "Dossiers EIMT : {place}" },
  "places.description": {
    en: "{place}: {approved} approved and {refused} refused LMIA records on ESDC's lists, {pending} pending Job Bank postings, with quarterly trends, occupations and employers.",
    fr: "{place} : {approved} EIMT approuvées et {refused} refusées aux listes d'EDSC, {pending} offres en attente au Guichet-Emplois, tendances, professions et employeurs.",
  },
  "places.lead_province": {
    en: "LMIA records for employers in {place}: ESDC's quarterly lists since 2014 and Job Bank postings.",
    fr: "Dossiers EIMT des employeurs, {place} : listes trimestrielles d'EDSC depuis 2014 et offres du Guichet-Emplois.",
  },
  "places.lead_cma": {
    en: "LMIA records for employers whose postal area lies in the {place} census metropolitan area: ESDC's quarterly lists since 2014 and Job Bank postings.",
    fr: "Dossiers EIMT des employeurs dont le secteur postal se trouve dans la région métropolitaine de recensement ({place}) : listes trimestrielles d'EDSC depuis 2014 et offres du Guichet-Emplois.",
  },
  "places.lead_city": {
    en: "LMIA records for employers in {place}, as the city is written on each record: ESDC's quarterly lists since 2014 and Job Bank postings.",
    fr: "Dossiers EIMT des employeurs, {place}, selon la ville inscrite à chaque dossier : listes trimestrielles d'EDSC depuis 2014 et offres du Guichet-Emplois.",
  },
  "places.in_cma": { en: "Census metropolitan area: {cma}.", fr: "Région métropolitaine de recensement : {cma}." },
  "places.thin": {
    en: "Only {n} records, below the {threshold} a page needs before search engines are invited to list it.",
    fr: "Seulement {n} dossiers, sous les {threshold} qu'il faut avant d'inviter les moteurs de recherche à répertorier la page.",
  },
  "places.summary": { en: "Summary", fr: "Sommaire" },
  "places.sum_records": { en: "Records (lists and postings)", fr: "Dossiers (listes et offres)" },
  "places.sum_employers": { en: "Employers", fr: "Employeurs" },
  "places.reading": { en: "What the Figures Show", fr: "Ce que montrent les chiffres" },
  "places.reading_none": { en: "Too few records to compare quarters.", fr: "Trop peu de dossiers pour comparer les trimestres." },
  "places.trend_up": {
    en: "Approved positions in {period}: {pos}, up {pct} percent from {prev} ({prevpos}).",
    fr: "Postes approuvés, {period} : {pos}, en hausse de {pct} % par rapport au {prev} ({prevpos}).",
  },
  "places.trend_down": {
    en: "Approved positions in {period}: {pos}, down {pct} percent from {prev} ({prevpos}).",
    fr: "Postes approuvés, {period} : {pos}, en baisse de {pct} % par rapport au {prev} ({prevpos}).",
  },
  "places.trend_same": { en: "Approved positions in {period}: {pos}, as in {prev}.", fr: "Postes approuvés, {period} : {pos}, comme au {prev}." },
  "places.trend_new": { en: "Approved positions in {period}: {pos}, against none in {prev}.", fr: "Postes approuvés, {period} : {pos}, contre aucun au {prev}." },
  "places.trend_only": { en: "Approved positions in {period}: {pos}.", fr: "Postes approuvés, {period} : {pos}." },
  "places.trend_none": { en: "Approved positions in {period}: none.", fr: "Postes approuvés, {period} : aucun." },
  "places.trend_refused": {
    en: "Refusal records in {period}: {refused}, against {prevrefused} in {prev}.",
    fr: "Inscriptions de refus, {period} : {refused}, contre {prevrefused} au {prev}.",
  },
  "places.trend_share": {
    en: "Share of all positions approved in Canada in {period}: {share} percent.",
    fr: "Part de tous les postes approuvés au Canada, {period} : {share} %.",
  },
  "places.top_occupation": {
    en: "Occupation with the most records here since {from}: {title} (NOC {noc}), {n}.",
    fr: "Profession comptant le plus de dossiers ici depuis le {from} : {title} (CNP {noc}), {n}.",
  },
  "places.context": {
    en: "Job vacancies counted by Statistics Canada in all occupations, {period}: {n} ({area}).",
    fr: "Postes vacants recensés par Statistique Canada, toutes professions, {period} : {n} ({area}).",
  },
  "places.context_wage": {
    en: "Job vacancies counted by Statistics Canada in all occupations, {period}: {n} ({area}), at an average offered wage of {wage}.",
    fr: "Postes vacants recensés par Statistique Canada, toutes professions, {period} : {n} ({area}), à un salaire horaire moyen offert de {wage}.",
  },
  "places.context_year": { en: "A year earlier: {before} vacancies.", fr: "Un an plus tôt : {before} postes vacants." },
  "places.lfs": {
    en: "Unemployment rate in the {name} census metropolitan area, three months ending {month}: {rate} percent (Labour Force Survey, unadjusted).",
    fr: "Taux de chômage de la région métropolitaine de recensement ({name}), trois mois se terminant en {month} : {rate} % (Enquête sur la population active, non désaisonnalisé).",
  },
  "places.lfs_rule": {
    en: "Since 2024-09-26 ESDC refuses to process low-wage applications in census metropolitan areas with an unemployment rate of 6 percent or more, outside exempt positions; the Methodology page lists them.",
    fr: "Depuis le 2024-09-26, EDSC refuse de traiter les demandes à bas salaire dans les régions métropolitaines de recensement dont le taux de chômage atteint 6 % ou plus, sauf pour les postes exemptés; la page Méthodologie les énumère.",
  },
  "places.region_of": { en: "{name} economic region", fr: "région économique {name}" },
  "places.level_province": { en: "provincial figure", fr: "chiffre provincial" },
  "places.level_canada": { en: "national figure", fr: "chiffre national" },
  "places.quality_e": {
    en: "Use with caution (Statistics Canada quality rating E)",
    fr: "À utiliser avec prudence (cote de qualité E de Statistique Canada)",
  },
  "places.wage_posted_one": {
    en: "Posted minimum on {n} LMIA-flagged Job Bank posting: {wage}.",
    fr: "Minimum affiché sur {n} offre du Guichet-Emplois visée par une EIMT : {wage}.",
  },
  "places.wage_posted_many": {
    en: "Median posted minimum on {n} LMIA-flagged Job Bank postings: {wage}.",
    fr: "Minimum affiché médian de {n} offres du Guichet-Emplois visées par une EIMT : {wage}.",
  },
  "places.wage_jobbank": { en: "Job Bank median: {median} ({area}).", fr: "Médiane du Guichet-Emplois : {median} ({area})." },
  "places.wage_jobbank_above": {
    en: "Job Bank median: {median} ({area}); the posted minimum is {pct} percent above it.",
    fr: "Médiane du Guichet-Emplois : {median} ({area}); le minimum affiché la dépasse de {pct} %.",
  },
  "places.wage_jobbank_below": {
    en: "Job Bank median: {median} ({area}); the posted minimum is {pct} percent below it.",
    fr: "Médiane du Guichet-Emplois : {median} ({area}); le minimum affiché lui est inférieur de {pct} %.",
  },
  "places.wage_jobbank_same": {
    en: "Job Bank median: {median} ({area}), equal to the posted minimum.",
    fr: "Médiane du Guichet-Emplois : {median} ({area}), égale au minimum affiché.",
  },
  "places.wage_statcan": {
    en: "Statistics Canada average offered wage, {period}: {wage} ({area}).",
    fr: "Salaire horaire moyen offert selon Statistique Canada, {period} : {wage} ({area}).",
  },
  "places.wage_statcan_above": {
    en: "Statistics Canada average offered wage, {period}: {wage} ({area}); the hourly posted minimum is {pct} percent above it.",
    fr: "Salaire horaire moyen offert selon Statistique Canada, {period} : {wage} ({area}); le minimum horaire affiché le dépasse de {pct} %.",
  },
  "places.wage_statcan_below": {
    en: "Statistics Canada average offered wage, {period}: {wage} ({area}); the hourly posted minimum is {pct} percent below it.",
    fr: "Salaire horaire moyen offert selon Statistique Canada, {period} : {wage} ({area}); le minimum horaire affiché lui est inférieur de {pct} %.",
  },
  "places.wage_statcan_same": {
    en: "Statistics Canada average offered wage, {period}: {wage} ({area}), equal to the hourly posted minimum.",
    fr: "Salaire horaire moyen offert selon Statistique Canada, {period} : {wage} ({area}), égal au minimum horaire affiché.",
  },
  "places.vacancies": {
    en: "Job vacancies counted by Statistics Canada, {period}: {n} ({area}).",
    fr: "Postes vacants recensés par Statistique Canada, {period} : {n} ({area}).",
  },
  "places.vacancies_year": {
    en: "Job vacancies counted by Statistics Canada, {period}: {n} ({area}), against {before} a year earlier.",
    fr: "Postes vacants recensés par Statistique Canada, {period} : {n} ({area}), contre {before} un an plus tôt.",
  },
  "places.by_quarter": { en: "Approvals and Refusals by Quarter", fr: "Approbations et refus par trimestre" },
  "places.bars_caption": {
    en: "Approved positions on ESDC's positive list, newest {n} periods.",
    fr: "Postes approuvés sur la liste positive d'EDSC, {n} dernières périodes.",
  },
  "places.older_quarters": { en: "Show {n} earlier periods", fr: "Afficher {n} périodes antérieures" },
  "places.col_quarter": { en: "Quarter", fr: "Trimestre" },
  "places.col_approved": { en: "Approved records", fr: "Inscriptions approuvées" },
  "places.col_approved_positions": { en: "Approved positions", fr: "Postes approuvés" },
  "places.col_refused": { en: "Refused records", fr: "Inscriptions refusées" },
  "places.col_refused_positions": { en: "Refused positions", fr: "Postes refusés" },
  "places.col_records": { en: "Records", fr: "Dossiers" },
  "places.col_latest_positions": { en: "Approved positions, {period}", fr: "Postes approuvés, {period}" },
  "places.col_city_pages": { en: "City pages", fr: "Pages de villes" },
  "places.col_occupation": { en: "Occupation", fr: "Profession" },
  "places.col_latest": { en: "Latest record", fr: "Dernier dossier" },
  "places.col_posted": { en: "Posted minimum (postings)", fr: "Minimum affiché (offres)" },
  "places.col_jobbank": { en: "Job Bank median", fr: "Médiane du Guichet-Emplois" },
  "places.col_statcan_wage": { en: "Offered wage (StatCan)", fr: "Salaire offert (StatCan)" },
  "places.col_vacancies": { en: "Vacancies (StatCan)", fr: "Postes vacants (StatCan)" },
  "places.span": { en: "{from} to {to}", fr: "du {from} au {to}" },
  "places.streams": { en: "Stream Mix", fr: "Répartition par volet" },
  "places.streams_note": { en: "Share of approved positions by TFWP stream, {span}.", fr: "Part des postes approuvés par volet du PTET, {span}." },
  "places.streams_none": { en: "No approvals in these quarters.", fr: "Aucune approbation pendant ces trimestres." },
  "places.stream_unstated": { en: "Stream not stated", fr: "Volet non précisé" },
  "places.records_one": { en: "{n} record", fr: "{n} dossier" },
  "places.records_many": { en: "{n} records", fr: "{n} dossiers" },
  "places.pct": { en: "{pct}%", fr: "{pct} %" },
  "places.occupations": { en: "Occupations and Wages", fr: "Professions et salaires" },
  "places.occupations_note": {
    en: "The 15 NOC 2021 occupations with the most records here since {from}. Job Bank and Statistics Canada figures are for this area: {area}.",
    fr: "Les 15 professions de la CNP 2021 comptant le plus de dossiers ici depuis le {from}. Les chiffres du Guichet-Emplois et de Statistique Canada portent sur cette zone : {area}.",
  },
  "places.occupations_none": { en: "No records with a NOC 2021 code here.", fr: "Aucun dossier portant un code de la CNP 2021 ici." },
  "places.wage_note": {
    en: "Posted minimum: the median of the lowest wage on LMIA-flagged Job Bank postings, with the number of postings in brackets, in the unit Job Bank uses for the occupation. Job Bank median: the wage table revised {table}, regional where published, else provincial, then national. Statistics Canada: average offered hourly wage and job vacancies, table 14-10-0444-01, newest quarter with a published figure (latest {quarter}); E marks a figure to use with caution. n/a: not published.",
    fr: "Minimum affiché : médiane du salaire le plus bas des offres du Guichet-Emplois visées par une EIMT, avec le nombre d'offres entre parenthèses, dans l'unité du Guichet-Emplois pour la profession. Médiane du Guichet-Emplois : table des salaires révisée le {table}, régionale si publiée, sinon provinciale, puis nationale. Statistique Canada : salaire horaire moyen offert et postes vacants, tableau 14-10-0444-01, dernier trimestre ayant un chiffre publié (au plus récent {quarter}); E signale un chiffre à utiliser avec prudence. s.o. : non publié.",
  },
  "places.employers": { en: "Employers With the Most Recent Records", fr: "Employeurs ayant les dossiers les plus récents" },
  "places.employers_note": {
    en: "Up to 20 employers, newest record first: a Job Bank posting flagged for an LMIA, or a row on ESDC's quarterly lists.",
    fr: "Jusqu'à 20 employeurs, le dossier le plus récent en premier : une offre du Guichet-Emplois portant une mention EIMT, ou une inscription aux listes trimestrielles d'EDSC.",
  },
  "places.seeker_h": { en: "Looking for Work?", fr: "Vous cherchez un emploi?" },
  "places.seeker_text": {
    en: "A past LMIA is not a job offer. These records show applications employers made and ESDC's decisions on them; they do not mean an employer is hiring now, and this site does not take applications.",
    fr: "Une EIMT passée n'est pas une offre d'emploi. Ces dossiers montrent les demandes des employeurs et les décisions d'EDSC; ils ne signifient pas qu'un employeur embauche en ce moment, et ce site ne reçoit pas de candidatures.",
  },
  "places.seeker_link": { en: "Search Job Bank's current postings for {what}", fr: "Chercher les offres actuelles du Guichet-Emplois : {what}" },
  "places.search": { en: "See these records in search ({place})", fr: "Voir ces dossiers dans la recherche ({place})" },
  "places.search_core": { en: "Search the records that name {place}", fr: "Chercher les dossiers qui mentionnent {place}" },
  "places.sources": {
    en: "Sources: ESDC's positive and negative LMIA employer lists, Job Bank postings and wages, Statistics Canada table 14-10-0444-01 and the NOC 2021 classification; licences on the {data}. How records are read: {method}.",
    fr: "Sources : listes des employeurs ayant reçu une EIMT positive ou négative d'EDSC, offres et salaires du Guichet-Emplois, tableau 14-10-0444-01 de Statistique Canada et classification CNP 2021; licences à la {data}. Lecture des dossiers : {method}.",
  },
  "places.sources_link": { en: "Data page", fr: "page Données" },
  "places.browse": { en: "Browse the records {occupations} or {places}.", fr: "Parcourir les dossiers {occupations} ou {places}." },
  "places.browse_occupations": { en: "by occupation", fr: "par profession" },
  "places.browse_places": { en: "by place", fr: "par lieu" },
  "places.data_sources": {
    en: "The occupation and place pages add Statistics Canada's {vacancies} and the {noc}, used under the {statcan}.",
    fr: "Les pages des professions et des lieux ajoutent le {vacancies} de Statistique Canada et la {noc}, utilisés sous la {statcan}.",
  },
  "places.src_vacancies": { en: "job vacancy and offered wage table 14-10-0444-01", fr: "tableau 14-10-0444-01 des postes vacants et du salaire offert" },
  "places.src_noc": { en: "NOC 2021 Version 1.0 classification structure", fr: "structure de classification de la CNP 2021 version 1.0" },
  "occ.index_title": { en: "LMIA Records by Occupation", fr: "Dossiers EIMT par profession" },
  "occ.index_seo_title": { en: "LMIA Records by Occupation (NOC 2021)", fr: "Dossiers EIMT par profession (CNP 2021)" },
  "occ.index_description": {
    en: "Approved and refused LMIAs and pending Job Bank postings for each NOC 2021 occupation, with quarterly trends, posted wages and the Job Bank median.",
    fr: "EIMT approuvées et refusées et offres en attente au Guichet-Emplois par profession de la CNP 2021, avec tendances, salaires affichés et médiane du Guichet-Emplois.",
  },
  "occ.index_lead": {
    en: "Every NOC 2021 occupation on ESDC's lists since {from} or on a Job Bank posting flagged for an LMIA, grouped by broad occupational category.",
    fr: "Chaque profession de la CNP 2021 inscrite aux listes d'EDSC depuis le {from} ou à une offre du Guichet-Emplois portant une mention EIMT, par grande catégorie professionnelle.",
  },
  "occ.noc_note": {
    en: "ESDC's lists give five-digit NOC 2021 codes from {from} on. Earlier lists use four-digit NOC 2011 codes, which do not map one to one onto NOC 2021, so earlier quarters are not counted here; the place pages and search cover every year.",
    fr: "Les listes d'EDSC donnent les codes à cinq chiffres de la CNP 2021 depuis le {from}. Les listes antérieures utilisent les codes à quatre chiffres de la CNP 2011, qui ne correspondent pas un à un à la CNP 2021 : les trimestres antérieurs ne sont donc pas comptés ici. Les pages des lieux et la recherche couvrent toutes les années.",
  },
  "occ.to_places": { en: "Browse by place instead", fr: "Parcourir plutôt par lieu" },
  "occ.not_found": { en: "Occupation Not Found", fr: "Profession introuvable" },
  "occ.back_index": { en: "See every occupation", fr: "Voir toutes les professions" },
  "occ.heading": { en: "{title} (NOC {noc})", fr: "{title} (CNP {noc})" },
  "occ.seo_title": { en: "LMIA Records for {title} (NOC {noc})", fr: "Dossiers EIMT : {title} (CNP {noc})" },
  "occ.description": {
    en: "{title} (NOC {noc}): {approved} approved and {refused} refused LMIA records since {from}, posted wages against the Job Bank median, and recent employers.",
    fr: "{title} (CNP {noc}) : {approved} EIMT approuvées et {refused} refusées depuis le {from}, salaires affichés et médiane du Guichet-Emplois, employeurs récents.",
  },
  "occ.definition_source": { en: "(NOC 2021 definition, Statistics Canada)", fr: "(définition de la CNP 2021, Statistique Canada)" },
  "occ.category": { en: "Broad category: {category}. TEER {teer}.", fr: "Grande catégorie : {category}. FEER {teer}." },
  "occ.teer": { en: "TEER {teer}.", fr: "FEER {teer}." },
  "occ.sum_records": { en: "Records since {from}", fr: "Dossiers depuis le {from}" },
  "occ.top_region": {
    en: "Economic region with the most records: {name}, {prov} ({n}, {share} percent of the total).",
    fr: "Région économique comptant le plus de dossiers : {name}, {prov} ({n}, {share} % du total).",
  },
  "occ.wages": { en: "Wages by Economic Region", fr: "Salaires par région économique" },
  "occ.wages_note": {
    en: "Canada, then the 15 economic regions with the most records for this occupation, placed by postal code. Job Bank and Statistics Canada figures fall back to the province, then Canada, where no regional figure is published.",
    fr: "Le Canada, puis les 15 régions économiques comptant le plus de dossiers pour cette profession, situées par code postal. Les chiffres du Guichet-Emplois et de Statistique Canada passent à la province, puis au Canada, faute de chiffre régional publié.",
  },
  "occ.col_area": { en: "Area", fr: "Zone" },
  "occ.no_posted": {
    en: "No LMIA-flagged Job Bank posting with this occupation and an hourly or yearly wage has been read yet; posting pages are read a few hundred a night.",
    fr: "Aucune offre du Guichet-Emplois visée par une EIMT avec cette profession et un salaire horaire ou annuel n'a encore été lue; les pages d'offres sont lues à raison de quelques centaines par nuit.",
  },
  "occ.series": { en: "Job Vacancies in Canada, Statistics Canada", fr: "Postes vacants au Canada, Statistique Canada" },
  "occ.series_note": {
    en: "Job vacancies and average offered hourly wage for this occupation across all employers in Canada, by quarter (table 14-10-0444-01, not seasonally adjusted). E: use with caution.",
    fr: "Postes vacants et salaire horaire moyen offert pour cette profession chez tous les employeurs au Canada, par trimestre (tableau 14-10-0444-01, données non désaisonnalisées). E : à utiliser avec prudence.",
  },
  "occ.series_none": {
    en: "Statistics Canada has not published a vacancy count for this occupation in these quarters.",
    fr: "Statistique Canada n'a pas publié de nombre de postes vacants pour cette profession pendant ces trimestres.",
  },
  "occ.provinces": { en: "Records by Province", fr: "Dossiers par province" },
  "occ.search": { en: "See every record for NOC {noc} in search", fr: "Voir tous les dossiers de la CNP {noc} dans la recherche" },
  "occ.offered": { en: "What LMIA Postings Offered", fr: "Ce que les offres visées par une EIMT proposaient" },
  "occ.offered_lead": {
    en: "Wages advertised on Job Bank postings for this occupation that carried an LMIA flag, requested or approved, when a nightly pass saw them. A posted range is the wage an employer advertised, which may differ from the pay a worker receives.",
    fr: "Salaires annoncés dans les offres du Guichet-Emplois pour cette profession qui portaient une mention EIMT, demandée ou approuvée, lors d'un passage nocturne. Une fourchette affichée est le salaire annoncé par l'employeur, qui peut différer de la rémunération versée au travailleur.",
  },
  "occ.offered_report": {
    en: "For the prevailing wage, see {link} and search for NOC {noc}.",
    fr: "Pour le salaire courant, consulter le {link} et chercher la CNP {noc}.",
  },
  "occ.offered_report_link": { en: "Job Bank's wage report", fr: "rapport sur les salaires du Guichet-Emplois" },
  "occ.offered_col_postings": { en: "Postings", fr: "Offres" },
  "occ.offered_col_hourly": { en: "Hourly postings", fr: "Offres horaires" },
  "occ.offered_col_min": { en: "Posted minimum, hourly (25th / median / 75th)", fr: "Minimum affiché, horaire (25e / médiane / 75e)" },
  "occ.offered_col_max": { en: "Posted maximum, hourly (25th / median / 75th)", fr: "Maximum affiché, horaire (25e / médiane / 75e)" },
  "occ.offered_col_other": { en: "Other units or no wage", fr: "Autres unités ou sans salaire" },
  "occ.offered_withheld": { en: "withheld", fr: "non diffusé" },
  "occ.offered_year": { en: "{n} per year", fr: "{n} par année" },
  "occ.offered_week": { en: "{n} per week", fr: "{n} par semaine" },
  "occ.offered_biweek": { en: "{n} every two weeks", fr: "{n} aux deux semaines" },
  "occ.offered_month": { en: "{n} per month", fr: "{n} par mois" },
  "occ.offered_semimonth": { en: "{n} twice a month", fr: "{n} deux fois par mois" },
  "occ.offered_day": { en: "{n} per day", fr: "{n} par jour" },
  "occ.offered_unstated": { en: "{n} with no wage", fr: "{n} sans salaire" },
  "occ.offered_rest_one": {
    en: "{n} of these postings lies in an economic region with fewer than {threshold} postings of this occupation, or has no postal code that places it, and counts in the Canada row only.",
    fr: "{n} de ces offres se trouve dans une région économique comptant moins de {threshold} offres de cette profession, ou n'a pas de code postal qui la situe, et n'est comptée que dans la ligne du Canada.",
  },
  "occ.offered_rest_many": {
    en: "{n} of these postings lie in economic regions with fewer than {threshold} postings of this occupation, or have no postal code that places them, and count in the Canada row only.",
    fr: "{n} de ces offres se trouvent dans des régions économiques comptant moins de {threshold} offres de cette profession, ou n'ont pas de code postal qui les situe, et ne sont comptées que dans la ligne du Canada.",
  },
  "occ.offered_none": {
    en: "No posting flagged for an LMIA with this occupation code has been read yet; posting pages are read a few hundred a night.",
    fr: "Aucune offre visée par une EIMT portant ce code de profession n'a encore été lue; les pages d'offres sont lues à raison de quelques centaines par nuit.",
  },
  "occ.offered_months": { en: "By Month", fr: "Par mois" },
  "occ.offered_months_note": {
    en: "Postings by the month (UTC) in which they were first seen, from {since}, when the nightly archive begins, with the median hourly posted minimum where a month holds at least {threshold} hourly postings.",
    fr: "Offres selon le mois (UTC) où elles ont été vues pour la première fois, depuis {since}, début des relevés nocturnes, avec le minimum horaire affiché médian lorsque le mois compte au moins {threshold} offres horaires.",
  },
  "occ.offered_col_month": { en: "Month", fr: "Mois" },
  "occ.offered_col_median": { en: "Median posted minimum, hourly", fr: "Minimum affiché médian, horaire" },
  "occ.offered_months_regions": { en: "Show the months by economic region", fr: "Afficher les mois par région économique" },
  "occ.offered_note": {
    en: "Counted: Job Bank postings with this occupation's NOC 2021 code, read from the posting page, that carried an LMIA flag, requested or approved, when a nightly pass saw them; a flag that lapsed later still counts. Each posting counts once, in the month it was first seen. Quartiles use hourly postings only: a quarter of the postings offered less than the 25th percentile and a quarter more than the 75th (linear interpolation between ranks). A posting stated per year, week, two weeks or month is counted under its unit and never converted to an hourly rate. Figures from fewer than {threshold} hourly postings are withheld and the count is shown; an economic region gets a row once it holds {threshold} postings. The Job Bank median and Statistics Canada's average offered wage are read as in the wage table above, for the same area. They are measured on other bases (wages in the occupation, wages offered on all vacancies) and are shown for context.",
    fr: "Comptées : offres du Guichet-Emplois portant le code CNP 2021 de cette profession, lu sur la page de l'offre, qui avaient une mention EIMT, demandée ou approuvée, lors d'un passage nocturne; une mention retirée par la suite n'enlève pas l'offre. Chaque offre est comptée une fois, dans le mois où elle a été vue pour la première fois. Les quartiles ne portent que sur les offres horaires : un quart des offres proposaient moins que le 25e centile et un quart plus que le 75e (interpolation linéaire entre les rangs). Une offre exprimée par année, par semaine, aux deux semaines ou par mois est comptée selon son unité et n'est jamais convertie en taux horaire. Les chiffres tirés de moins de {threshold} offres horaires ne sont pas diffusés et le nombre est indiqué; une région économique obtient une ligne dès qu'elle compte {threshold} offres. La médiane du Guichet-Emplois et le salaire horaire moyen offert de Statistique Canada sont lus comme dans le tableau des salaires ci-dessus, pour la même zone. Ils reposent sur d'autres bases (salaires dans la profession, salaires offerts pour l'ensemble des postes vacants) et sont donnés à titre de contexte.",
  },

  // --- household exclusion ---
  "data.change_households": {
    en: "Private households left out of the ESDC lists: a row whose occupation is home child care provider or home support worker (NOC 4411, 4412, 44100 or 44101) and whose employer is named as a person, with no business name or legal form, is no longer loaded or counted. 24 rows (28 positions) and 22 employer profiles removed: 22 rows and 23 positions from the positive lists, 2 rows and 5 positions from the negative lists. The mirrored ESDC files are unchanged.",
    fr: "Ménages privés écartés des listes d'EDSC : une inscription dont la profession est gardien d'enfants en milieu familial ou aide de maintien à domicile (CNP 4411, 4412, 44100 ou 44101) et dont l'employeur est désigné par un nom de personne, sans nom d'entreprise ni forme juridique, n'est plus chargée ni comptée. 24 inscriptions (28 postes) et 22 profils d'employeurs retirés : 22 inscriptions et 23 postes des listes positives, 2 inscriptions et 5 postes des listes négatives. Les fichiers d'EDSC reproduits sont inchangés.",
  },
  "data.recomputed_households": {
    en: "Counts, rankings, quarterly releases, employer profiles, downloads",
    fr: "Chiffres, classements, publications trimestrielles, profils d'employeurs, téléchargements",
  },

  // --- esdc reload ---
  "data.change_esdc_rows": {
    en: "ESDC lists from 2016 to 2019 Q2 name an employer, its address and province only on the first of its rows, and the stream only at the top of each block. The rows below are now loaded ({rows} rows, {positions} positions), and {streams} rows already loaded gained their stream and {provinces} their province. {headers} rows from 2016 to 2026 that the loader had taken for column headings are loaded too ({header_positions} positions). Some employer IDs changed.",
    fr: "Les listes d'EDSC de 2016 au T2 2019 n'indiquent un employeur, son adresse et sa province qu'à la première de ses inscriptions, et le volet qu'en tête de chaque bloc. Les inscriptions suivantes sont maintenant chargées ({rows} inscriptions, {positions} postes), et {streams} inscriptions déjà chargées ont reçu leur volet et {provinces} leur province. {headers} inscriptions de 2016 à 2026 que le chargement prenait pour des en-têtes de colonnes sont aussi chargées ({header_positions} postes). Certains identifiants d'employeur ont changé.",
  },
  "data.recomputed_esdc_rows": {
    en: "ESDC records 2016 to 2026, employer profiles, rankings",
    fr: "Inscriptions d'EDSC de 2016 à 2026, profils d'employeurs, classements",
  },
  "data.change_trends": {
    en: "New Trends page: ESDC's approvals and refusals since 2014 as series, by stream and by province, compared year over year and marked with dated rule changes, and the nightly count of Job Bank postings flagged LMIA requested on each complete pass.",
    fr: "Nouvelle page Tendances : approbations et refus d'EDSC depuis 2014 en séries, par volet et par province, comparés d'une année à l'autre et accompagnés des changements de règles datés, et le relevé quotidien des offres du Guichet-Emplois portant la mention « EIMT demandée » à chaque passage complet.",
  },
  "data.recomputed_trends": {
    en: "Nothing recomputed; new files under trends/",
    fr: "Aucun recalcul; nouveaux fichiers sous trends/",
  },
  "data.change_program": {
    en: "New Program conditions page: LMIA processing times by stream, the census metropolitan areas where low-wage LMIAs are not processed, and the provincial and territorial wage thresholds, read nightly from canada.ca with every edition kept. Indicator rules v{rules}: the low-wage stream indicator reads ESDC's published lists for each quarter they cover and keeps Statistics Canada's rates for earlier quarters.",
    fr: "Nouvelle page Conditions du programme : délais de traitement des EIMT par volet, régions métropolitaines de recensement où les EIMT à bas salaire ne sont pas traitées et seuils salariaux provinciaux et territoriaux, relevés chaque nuit sur canada.ca, chaque édition étant conservée. Règles des indicateurs v{rules} : l'indicateur du volet des postes à bas salaire lit les listes publiées par EDSC pour chaque trimestre qu'elles couvrent et conserve les taux de Statistique Canada pour les trimestres antérieurs.",
  },
  "data.recomputed_program": {
    en: "Low-wage stream indicator; new file program/index.json",
    fr: "Indicateur du volet des postes à bas salaire; nouveau fichier program/index.json",
  },

  // --- trends ---
  "nav.trends": { en: "Trends", fr: "Tendances" },
  "trends.crumb": { en: "Trends", fr: "Tendances" },
  "trends.h1": { en: "LMIA Trends Since {start}", fr: "Tendances des EIMT depuis {start}" },
  "trends.h1_streams": { en: "LMIA Trends by Stream", fr: "Tendances des EIMT par volet" },
  "trends.h1_provinces": { en: "LMIA Trends by Province", fr: "Tendances des EIMT par province" },
  "trends.h1_pending": {
    en: "Job Bank Postings Flagged LMIA Requested",
    fr: "Offres du Guichet-Emplois portant la mention « EIMT demandée »",
  },
  "trends.lead": {
    en: "Every ESDC list of approved and refused LMIAs since {start} as one series, and the nightly count of Job Bank postings flagged LMIA requested. Each row on ESDC's lists is one employer's approval or refusal for an occupation at a location.",
    fr: "Toutes les listes d'EDSC des EIMT approuvées et refusées depuis {start} en une seule série, et le relevé quotidien des offres du Guichet-Emplois portant la mention « EIMT demandée ». Chaque inscription des listes d'EDSC est l'approbation ou le refus d'un employeur pour une profession à un lieu donné.",
  },
  "trends.views": { en: "Views", fr: "Vues" },
  "trends.view.national": { en: "All of Canada", fr: "Ensemble du Canada" },
  "trends.view.streams": { en: "By stream", fr: "Par volet" },
  "trends.view.provinces": { en: "By province", fr: "Par province" },
  "trends.view.pending": { en: "Job Bank pending, nightly", fr: "En attente au Guichet-Emplois, chaque nuit" },
  "trends.not_found": { en: "No Such Trends View", fr: "Vue de tendances introuvable" },
  "trends.not_found_text": {
    en: "The {trends} lists the views: all of Canada, by stream, by province, and Job Bank pending postings.",
    fr: "La {trends} énumère les vues : ensemble du Canada, par volet, par province, et offres en attente au Guichet-Emplois.",
  },
  "trends.page_link": { en: "Trends page", fr: "page Tendances" },
  "trends.not_published": { en: "This view has not been published yet.", fr: "Cette vue n'est pas encore publiée." },

  "trends.yoy_title": { en: "Year over Year", fr: "D'une année à l'autre" },
  "trends.yoy_quarter": {
    en: "In {now}, {pos} positions were approved on {rows} rows of ESDC's positive list, against {pos_then} on {rows_then} rows in {then}, the same quarter a year earlier ({change}).",
    fr: "Au {now}, {pos} postes ont été approuvés sur {rows} inscriptions de la liste positive d'EDSC, contre {pos_then} sur {rows_then} inscriptions au {then}, le même trimestre un an plus tôt ({change}).",
  },
  "trends.yoy_employers": {
    en: "Employers with an approval: {n}, against {then_n} ({change}).",
    fr: "Employeurs ayant une approbation : {n}, contre {then_n} ({change}).",
  },
  "trends.yoy_refused": {
    en: "Rows on the negative list (refusals): {n} in {now}, against {then_n} in {then} ({change}).",
    fr: "Inscriptions sur la liste négative (refus) : {n} au {now}, contre {then_n} au {then} ({change}).",
  },
  "trends.yoy_ytd": {
    en: "From {first} to {now}, {pos} positions were approved on {rows} rows, against {pos_then} on {rows_then} rows in the same quarters of {year_then} ({change}).",
    fr: "Du {first} au {now}, {pos} postes ont été approuvés sur {rows} inscriptions, contre {pos_then} sur {rows_then} inscriptions aux mêmes trimestres de {year_then} ({change}).",
  },
  "trends.yoy_ytd_refused": {
    en: "Refused rows over the same quarters: {n}, against {then_n} ({change}).",
    fr: "Inscriptions refusées aux mêmes trimestres : {n}, contre {then_n} ({change}).",
  },
  "trends.yoy_ytd_one": {
    en: "So far {year} has only its first quarter, so the year to date is the comparison above.",
    fr: "Pour l'instant, l'année {year} ne compte que son premier trimestre : le cumul de l'année est donc la comparaison ci-dessus.",
  },
  "trends.yoy_ytd_full": {
    en: "The latest list completes {year}, so the year to date is the full-year comparison below.",
    fr: "La dernière liste complète l'année {year} : le cumul de l'année est donc la comparaison annuelle ci-dessous.",
  },
  "trends.yoy_year": {
    en: "In {year}, {pos} positions were approved on {rows} rows, against {pos_then} on {rows_then} rows in {year_then} ({change}).",
    fr: "En {year}, {pos} postes ont été approuvés sur {rows} inscriptions, contre {pos_then} sur {rows_then} inscriptions en {year_then} ({change}).",
  },
  "trends.yoy_year_refused": {
    en: "Refused rows: {n}, against {then_n} ({change}).",
    fr: "Inscriptions refusées : {n}, contre {then_n} ({change}).",
  },
  "trends.yoy_no_refused": {
    en: "No comparison of refusals: ESDC published no negative list for {periods}.",
    fr: "Aucune comparaison des refus : EDSC n'a publié aucune liste négative pour {periods}.",
  },
  "trends.yoy_season": {
    en: "Farm approvals peak in the first half of the year, so each quarter is set against the same quarter a year earlier, not against the quarter before.",
    fr: "Les approbations agricoles culminent au premier semestre : chaque trimestre est donc comparé au même trimestre un an plus tôt, et non au trimestre précédent.",
  },
  "trends.change_up": { en: "up {pct} percent", fr: "en hausse de {pct} %" },
  "trends.change_down": { en: "down {pct} percent", fr: "en baisse de {pct} %" },
  "trends.change_same": { en: "no change", fr: "aucune variation" },
  "trends.change_flat": { en: "about the same", fr: "à peu près inchangé" },
  "trends.change_from_zero": { en: "from zero", fr: "à partir de zéro" },

  "trends.notes_title": { en: "About These Series", fr: "À propos de ces séries" },
  "trends.note_spans": {
    en: "The 2014 file covers June 20 to December 31, 2014, the 2015 and 2016 files a year each, and one file covers {half}; every later file is one quarter. On the charts a file covering more than one quarter is drawn lighter, across the quarters it covers, at its average per quarter. The tables give each file's total.",
    fr: "Le fichier de 2014 couvre du 20 juin au 31 décembre 2014, ceux de 2015 et 2016 une année chacun, et un fichier couvre les {half}; chaque fichier suivant couvre un trimestre. Sur les graphiques, un fichier qui couvre plus d'un trimestre est tracé en plus pâle, sur les trimestres qu'il couvre, à sa moyenne par trimestre. Les tableaux donnent le total de chaque fichier.",
  },
  "trends.note_streams": {
    en: "Streams exist only from 2017: the 2014 to 2016 files have no stream column, so the view by stream starts with the {from} file.",
    fr: "Les volets n'existent qu'à partir de 2017 : les fichiers de 2014 à 2016 n'ont pas de colonne de volet. La vue par volet commence donc avec le fichier {from}.",
  },
  "trends.note_reload": {
    en: "The 2016 to 2019 files became complete here on 2026-10-19, when the rows ESDC prints without repeating the employer's name (one per further occupation) were loaded; figures for those years taken from this site before then are lower. See the {changelog}.",
    fr: "Les fichiers de 2016 à 2019 sont complets ici depuis le 2026-10-19, date du chargement des inscriptions qu'EDSC imprime sans répéter le nom de l'employeur (une par profession supplémentaire); les chiffres de ces années tirés du site avant cette date sont inférieurs. Voir le {changelog}.",
  },
  "trends.changelog_link": { en: "changelog on the Data page", fr: "journal des modifications de la page Données" },
  "trends.note_noc": {
    en: "Occupation series break at {from}: from that file ESDC codes occupations in NOC 2021 instead of NOC 2011, and the two do not match code for code. The counts on this page do not depend on the occupation code.",
    fr: "Les séries par profession sont rompues au {from} : à partir de ce fichier, EDSC code les professions selon la CNP 2021 plutôt que la CNP 2011, et les deux ne se correspondent pas code pour code. Les chiffres de cette page ne dépendent pas du code de profession.",
  },
  "trends.note_program": {
    en: "The quarterly lists of census metropolitan areas where low-wage LMIAs are not processed are a series rather than single rule changes, so they are not marked on the charts; the {program} page has every list read, with the wage thresholds and the processing times.",
    fr: "Les listes trimestrielles des régions métropolitaines de recensement où les EIMT à bas salaire ne sont pas traitées forment une série plutôt que des changements de règles ponctuels; elles ne sont donc pas marquées sur les graphiques. La page {program} présente chaque liste relevée, avec les seuils salariaux et les délais de traitement.",
  },
  "trends.program_link": { en: "Program conditions", fr: "Conditions du programme" },
  "trends.note_refused_missing": {
    en: "ESDC published no negative list for {periods}, so the refusals for it are left blank rather than shown as zero.",
    fr: "EDSC n'a publié aucune liste négative pour {periods} : les refus correspondants sont donc laissés en blanc plutôt qu'à zéro.",
  },

  "trends.chart_periods": { en: "Approved and Refused LMIAs Since 2014", fr: "EIMT approuvées et refusées depuis 2014" },
  "trends.chart_aria": {
    en: "Bar chart; the table under the chart gives every figure.",
    fr: "Graphique à barres; le tableau sous le graphique donne chaque chiffre.",
  },
  "trends.line_aria": {
    en: "Line chart; the table under the chart gives every figure.",
    fr: "Graphique linéaire; le tableau sous le graphique donne chaque chiffre.",
  },
  "trends.legend_light": {
    en: "Lighter bars: a file covering more than one quarter, at its average per quarter.",
    fr: "Barres plus pâles : fichier couvrant plus d'un trimestre, à sa moyenne par trimestre.",
  },
  "trends.legend_marks": {
    en: "Numbered dashed lines: the rule changes listed under the chart.",
    fr: "Lignes pointillées numérotées : changements de règles énumérés sous le graphique.",
  },
  "trends.legend_scale": { en: "Each panel has its own scale.", fr: "Chaque panneau a sa propre échelle." },
  "trends.bar_title": { en: "{period}: {n}", fr: "{period} : {n}" },
  "trends.bar_title_avg": {
    en: "{period}: {n} ({avg} per quarter over {q} quarters)",
    fr: "{period} : {n} ({avg} par trimestre sur {q} trimestres)",
  },
  "trends.table_periods": { en: "Figures by File", fr: "Chiffres par fichier" },
  "trends.col_period": { en: "File", fr: "Fichier" },
  "trends.col_quarters": { en: "Quarters", fr: "Trimestres" },
  "trends.col_year": { en: "Year", fr: "Année" },
  "trends.col_files": { en: "Files", fr: "Fichiers" },
  "trends.col_cover": { en: "Coverage", fr: "Couverture" },
  "trends.col_total": { en: "All streams", fr: "Tous les volets" },
  "trends.col_all": { en: "All", fr: "Ensemble" },
  "trends.col_no_stream": { en: "No stream", fr: "Sans volet" },
  "trends.col_pct": { en: "Change (%)", fr: "Variation (%)" },
  "trends.cover_full": { en: "Full year", fr: "Année complète" },
  "trends.cover_2014": { en: "June 20 to December 31", fr: "Du 20 juin au 31 décembre" },
  "trends.cover_to": { en: "To {period}", fr: "Jusqu'au {period}" },
  "trends.chart_years": { en: "Positions Approved by Calendar Year", fr: "Postes approuvés par année civile" },
  "trends.legend_years": {
    en: "Lighter bars: a year the lists do not cover in full (2014 from June 20; the current year so far).",
    fr: "Barres plus pâles : année que les listes ne couvrent pas en entier (2014 à partir du 20 juin; l'année en cours jusqu'ici).",
  },
  "trends.table_years": { en: "Figures by Calendar Year", fr: "Chiffres par année civile" },

  "trends.marks_title": { en: "Rule Changes on the Charts", fr: "Changements de règles sur les graphiques" },
  "trends.marks_note": {
    en: "Each line is dated by when the change took effect, as the Government of Canada announced it. A drop after a line can come from the rule, from the economy, or from both; the charts do not separate them.",
    fr: "Chaque ligne est datée de l'entrée en vigueur du changement, tel que le gouvernement du Canada l'a annoncé. Une baisse après une ligne peut tenir à la règle, à la conjoncture, ou aux deux; les graphiques ne les distinguent pas.",
  },
  "trends.mark.roadmap": {
    en: "Workforce Solutions Road Map: LMIAs valid 18 months instead of 9, and no limit on low-wage positions in seasonal industries; from April 30, 2022, the cap on low-wage workers rose to 20 percent of an employer's workforce, and to 30 percent in seven sectors with shortages.",
    fr: "Plan d'action pour les employeurs et la main-d'œuvre : EIMT valides 18 mois plutôt que 9, et plus de limite aux postes à bas salaire dans les industries saisonnières; à partir du 30 avril 2022, le plafond de travailleurs à bas salaire passe à 20 % de l'effectif d'un employeur, et à 30 % dans sept secteurs en pénurie.",
  },
  "trends.mark.noc": {
    en: "ESDC's lists code occupations in NOC 2021 from the {period} file on (NOC 2011 before). A change of classification: the counts on this page are not affected, but occupation series break here.",
    fr: "Les listes d'EDSC codent les professions selon la CNP 2021 à partir du fichier {period} (CNP 2011 auparavant). Il s'agit d'un changement de classification : les chiffres de cette page n'en sont pas touchés, mais les séries par profession sont rompues.",
  },
  "trends.mark.validity": {
    en: "LMIAs valid 6 months instead of 12; the cap on low-wage workers fell from 30 to 20 percent for the employers covered by the 2022 road map, except in construction and health care.",
    fr: "EIMT valides 6 mois plutôt que 12; le plafond de travailleurs à bas salaire passe de 30 à 20 % pour les employeurs visés par le plan d'action de 2022, sauf dans la construction et les soins de santé.",
  },
  "trends.mark.cma": {
    en: "No processing of low-wage LMIA applications in census metropolitan areas with an unemployment rate of 6 percent or more, with exceptions for food security sectors, construction and health care; the cap on low-wage workers lowered to 10 percent of an employer's workforce (20 percent in health care, construction and food processing); low-wage positions limited to one year instead of two.",
    fr: "Aucun traitement des demandes d'EIMT pour des postes à bas salaire dans les régions métropolitaines de recensement dont le taux de chômage atteint 6 % ou plus, sauf dans les secteurs de la sécurité alimentaire, la construction et les soins de santé; plafond de travailleurs à bas salaire abaissé à 10 % de l'effectif d'un employeur (20 % dans les soins de santé, la construction et la transformation des aliments); postes à bas salaire limités à un an plutôt que deux.",
  },
  "trends.mark.highwage": {
    en: "The High Wage stream's threshold raised to 20 percent above the provincial or territorial median hourly wage, so positions paid between the old and the new threshold count as Low Wage.",
    fr: "Le seuil du volet des postes à haut salaire passe à 20 % au-dessus du salaire horaire médian de la province ou du territoire : les postes payés entre l'ancien et le nouveau seuil relèvent donc du volet des postes à bas salaire.",
  },
  "trends.mark.lowwage_2026": {
    en: "Low-wage stream: job advertisements must run for at least 8 consecutive weeks in the 3 months before an application, and recruitment must target youth; the cap on low-wage temporary foreign workers stays at 10 percent of a work location's workforce (20 percent in construction, food manufacturing, hospitals and nursing care), and rural employers in participating provinces and territories may keep their current share or use a 15 percent cap until 2027-03-31 (start dates vary by province).",
    fr: "Volet des postes à bas salaire : les offres d'emploi doivent être affichées pendant au moins 8 semaines consécutives dans les 3 mois précédant la demande, et le recrutement doit cibler les jeunes; le plafond de travailleurs étrangers temporaires à bas salaire reste à 10 % de l'effectif d'un lieu de travail (20 % dans la construction, la fabrication d'aliments, les hôpitaux et les soins infirmiers), et les employeurs des régions rurales des provinces et territoires participants peuvent conserver leur proportion actuelle ou appliquer un plafond de 15 % jusqu'au 2027-03-31 (dates de début selon la province).",
  },
  "trends.mark.thresholds_2025": {
    en: "New provincial and territorial hourly wage thresholds (the median hourly wage plus 20 percent) divide the high-wage and low-wage streams for LMIAs received from this date to 2026-07-16; the Program conditions page lists them.",
    fr: "De nouveaux seuils salariaux horaires provinciaux et territoriaux (le salaire horaire médian majoré de 20 %) séparent les volets des postes à haut et à bas salaire pour les EIMT reçues de cette date au 2026-07-16; la page Conditions du programme les énumère.",
  },
  "trends.mark.thresholds_2026": {
    en: "New provincial and territorial hourly wage thresholds (the median hourly wage plus 20 percent, from the Labour Force Survey for 2024 to 2025) divide the high-wage and low-wage streams for LMIAs received from this date; the Program conditions page lists them.",
    fr: "De nouveaux seuils salariaux horaires provinciaux et territoriaux (le salaire horaire médian majoré de 20 %, selon l'Enquête sur la population active de 2024 à 2025) séparent les volets des postes à haut et à bas salaire pour les EIMT reçues à compter de cette date; la page Conditions du programme les énumère.",
  },
  "trends.source_release": { en: "ESDC news release of {date}", fr: "communiqué d'EDSC du {date}" },
  "trends.source_requirements": {
    en: "program requirements for low-wage positions (canada.ca)",
    fr: "exigences du programme pour les postes à bas salaire (canada.ca)",
  },
  "trends.source_rural": {
    en: "temporary measures for rural employers (canada.ca)",
    fr: "mesures temporaires pour les employeurs ruraux (canada.ca)",
  },
  "trends.source_thresholds": {
    en: "hourly wage thresholds by province or territory (canada.ca)",
    fr: "seuils salariaux horaires par province ou territoire (canada.ca)",
  },
  "trends.source_dataset": {
    en: "ESDC positive LMIA employers list, Open Government Portal",
    fr: "liste des employeurs ayant reçu une EIMT positive d'EDSC, Portail du gouvernement ouvert",
  },
  "trends.source_label": { en: "Source: {links}.", fr: "Source : {links}." },
  "trends.sources_label": { en: "Sources: {links}.", fr: "Sources : {links}." },

  "trends.streams_lead": {
    en: "Positions approved in each stream, from the {from} file, the first to carry a stream column.",
    fr: "Postes approuvés dans chaque volet, à partir du fichier {from}, le premier à comporter une colonne de volet.",
  },
  "trends.provinces_lead": {
    en: "Positions approved by the province or territory of the business location, in every ESDC file since {start}.",
    fr: "Postes approuvés selon la province ou le territoire du lieu de l'entreprise, dans chaque fichier d'EDSC depuis {start}.",
  },
  "trends.same_quarter": { en: "{now} Against {then}", fr: "{now} par rapport au {then}" },
  "trends.same_quarter_note": {
    en: "Positions approved in the latest quarter and in the same quarter a year earlier.",
    fr: "Postes approuvés au dernier trimestre et au même trimestre un an plus tôt.",
  },
  "trends.chart_streams": { en: "Positions Approved by Stream", fr: "Postes approuvés par volet" },
  "trends.chart_provinces": {
    en: "Positions Approved by Province or Territory",
    fr: "Postes approuvés par province ou territoire",
  },
  "trends.table_streams": { en: "Positions Approved by Stream", fr: "Postes approuvés par volet" },
  "trends.table_provinces": { en: "Positions Approved by Province or Territory", fr: "Postes approuvés par province ou territoire" },
  "trends.refused_streams": { en: "Refused rows by stream", fr: "Inscriptions refusées par volet" },
  "trends.refused_provinces": { en: "Refused rows by province or territory", fr: "Inscriptions refusées par province ou territoire" },
  "trends.codes_note": {
    en: "Columns use the two-letter codes; XX is a head office outside Canada.",
    fr: "Les colonnes portent les codes à deux lettres; XX désigne un siège social à l'extérieur du Canada.",
  },

  "trends.pending_lead": {
    en: "The number of Job Bank postings carrying the \"LMIA requested\" flag, counted on each complete nightly pass over Job Bank's search. Job Bank shows only the postings open today; this series is the site's own count, kept since {first}.",
    fr: "Le nombre d'offres du Guichet-Emplois portant la mention « EIMT demandée », compté à chaque passage nocturne complet sur la recherche du Guichet-Emplois. Le Guichet-Emplois ne montre que les offres ouvertes aujourd'hui; cette série est le relevé du site, tenu depuis le {first}.",
  },
  "trends.pending_latest": {
    en: "Latest complete pass, {date}: {n} postings, against {prev_n} on {prev} ({change}).",
    fr: "Dernier passage complet, {date} : {n} offres, contre {prev_n} le {prev} ({change}).",
  },
  "trends.pending_latest_one": { en: "First complete pass, {date}: {n} postings.", fr: "Premier passage complet, {date} : {n} offres." },
  "trends.pending_began": {
    en: "The series began on {first} with the first complete pass and gains a point each night.",
    fr: "La série a commencé le {first} avec le premier passage complet et gagne un point chaque nuit.",
  },
  "trends.pending_rule": {
    en: "A pass counts when it ran to the end without a failed request and listed at least half as many postings as the passes in the two weeks around it, which leaves out short test sweeps and passes the host cut off. Each point is dated by the day (UTC) its pass ended.",
    fr: "Un passage compte quand il s'est rendu au bout sans requête échouée et a relevé au moins la moitié autant d'offres que les passages des deux semaines qui l'entourent, ce qui écarte les courts balayages d'essai et les passages interrompus par le serveur. Chaque point est daté du jour (UTC) où son passage a pris fin.",
  },
  "trends.pending_households": {
    en: "Postings by private households are never stored, so they are not in the count.",
    fr: "Les offres des ménages privés ne sont jamais conservées : elles ne figurent donc pas dans le compte.",
  },
  "trends.pending_caution": {
    en: "A flagged posting shows that the employer requested an LMIA for the job. It is not a decision: ESDC may approve or refuse the request, and one posting can be for several positions.",
    fr: "Une offre visée indique que l'employeur a demandé une EIMT pour le poste. Ce n'est pas une décision : EDSC peut approuver ou refuser la demande, et une offre peut viser plusieurs postes.",
  },
  "trends.chart_pending": {
    en: "Flagged Postings Counted Each Night",
    fr: "Offres portant la mention, comptées chaque nuit",
  },
  "trends.panel_pending": { en: "Postings flagged", fr: "Offres visées" },
  "trends.table_pending": { en: "Figures by Pass", fr: "Chiffres par passage" },
  "trends.col_vs_prev": { en: "Change from the previous pass", fr: "Variation depuis le passage précédent" },
  "trends.pending_search": { en: "See today's pending postings", fr: "Voir les offres en attente aujourd'hui" },
  "trends.pending_none": { en: "No complete pass is recorded yet.", fr: "Aucun passage complet n'est encore enregistré." },

  "trends.sources": {
    en: "Sources: ESDC's positive and negative LMIA employer lists (Open Government Licence, Canada) and Job Bank's search, read nightly; licences on the {data}. Rule changes: Government of Canada news releases and program pages, linked above.",
    fr: "Sources : listes des employeurs ayant reçu une EIMT positive ou négative d'EDSC (Licence du gouvernement ouvert, Canada) et recherche du Guichet-Emplois, lue chaque nuit; licences à la {data}. Changements de règles : communiqués et pages de programme du gouvernement du Canada, en lien ci-dessus.",
  },
  "trends.sources_pending": {
    en: "Source: Job Bank's search, read each night by this site; licences on the {data}.",
    fr: "Source : recherche du Guichet-Emplois, lue chaque nuit par ce site; licences à la {data}.",
  },
  "trends.pr_gap": {
    en: "ESDC's lists carry no Permanent Resident Only rows in the files from 2017 Q4 to 2023 Q3, so that panel is empty for those years; the gap is in the published files.",
    fr: "Les listes d'EDSC ne contiennent aucune ligne du volet Résidence permanente seulement dans les fichiers du T4 2017 au T3 2023; ce panneau est donc vide pour ces années, et la lacune vient des fichiers publiés.",
  },
  "trends.small_streams": {
    en: "{names}: under 0.1 percent of the positions, so in the tables only.",
    fr: "{names} : moins de 0,1 % des postes, donc dans les tableaux seulement.",
  },
  "trends.seo_title": {
    en: "LMIA Trends Since {start}: Approvals and Refusals by Quarter",
    fr: "Tendances des EIMT depuis {start} : approbations et refus par trimestre",
  },
  "trends.seo_desc": {
    en: "Approved positions and refused LMIAs in every ESDC list since {start}, compared year over year, with the dated rule changes that shaped them.",
    fr: "Postes approuvés et EIMT refusées dans chaque liste d'EDSC depuis {start}, comparés d'une année à l'autre, avec les changements de règles datés.",
  },
  "trends.seo_title_streams": { en: "LMIA Approvals by Stream Since 2017", fr: "EIMT approuvées par volet depuis 2017" },
  "trends.seo_desc_streams": {
    en: "Positions approved in each LMIA stream (high wage, low wage, primary agriculture, Global Talent) in every ESDC list since 2017, year over year.",
    fr: "Postes approuvés dans chaque volet des EIMT (haut salaire, bas salaire, agriculture primaire, talents mondiaux) dans chaque liste d'EDSC depuis 2017.",
  },
  "trends.seo_title_provinces": { en: "LMIA Approvals by Province Since {start}", fr: "EIMT approuvées par province depuis {start}" },
  "trends.seo_desc_provinces": {
    en: "Positions approved on ESDC's LMIA lists in each province and territory since {start}, with year-over-year comparisons and the rule changes marked.",
    fr: "Postes approuvés sur les listes EIMT d'EDSC dans chaque province et territoire depuis {start}, avec les comparaisons d'une année à l'autre et les changements de règles.",
  },
  "trends.seo_title_pending": {
    en: "Job Bank Postings Flagged LMIA Requested, Nightly Count",
    fr: "Offres du Guichet-Emplois avec mention « EIMT demandée », relevé quotidien",
  },
  "trends.seo_desc_pending": {
    en: "The number of Job Bank postings flagged LMIA requested on each complete nightly pass since {first}, counted by LMIA Watch.",
    fr: "Le nombre d'offres du Guichet-Emplois portant la mention « EIMT demandée » à chaque passage nocturne complet depuis le {first}.",
  },
  "trends.home_link": {
    en: "Approvals and refusals since 2014, year over year",
    fr: "Approbations et refus depuis 2014, d'une année à l'autre",
  },
  "trends.releases_link": {
    en: "Trends: every release as one series, year over year",
    fr: "Tendances : toutes les publications en une série, d'une année à l'autre",
  },

  // --- program conditions (pages/program.tsx) ---
  "program.crumb": { en: "Program conditions", fr: "Conditions du programme" },
  "program.h1": { en: "Program Conditions", fr: "Conditions du programme" },
  "program.lead": {
    en: "What the Temporary Foreign Worker Program's own pages on canada.ca state, read each night: LMIA processing times by stream, the census metropolitan areas where low-wage LMIA applications are not processed, and the wage thresholds between the high-wage and low-wage streams. Every figure links to the page it was read from, with the date it was read.",
    fr: "Ce que les pages du Programme des travailleurs étrangers temporaires sur canada.ca indiquent, relevé chaque nuit : les délais de traitement des EIMT par volet, les régions métropolitaines de recensement où les demandes d'EIMT à bas salaire ne sont pas traitées et les seuils salariaux entre les volets des postes à haut et à bas salaire. Chaque chiffre renvoie à la page où il a été relevé, avec la date du relevé.",
  },
  "program.now_title": { en: "In Force on {date}", fr: "En vigueur le {date}" },
  "program.as_of_note": {
    en: "Worked out for the date of the latest nightly export.",
    fr: "Établi pour la date de la plus récente exportation de nuit.",
  },
  "program.range": { en: "from {from} to {to}", fr: "du {from} au {to}" },
  "program.range_open": { en: "from {from}", fr: "à compter du {from}" },
  "program.now_cma": {
    en: "Low-wage LMIA applications are not processed in {n} of {total} census metropolitan areas (unemployment rate of {threshold} percent or more), for applications submitted {range}.",
    fr: "Les demandes d'EIMT à bas salaire ne sont pas traitées dans {n} des {total} régions métropolitaines de recensement (taux de chômage de {threshold} % ou plus), pour les demandes soumises {range}.",
  },
  "program.now_wage": {
    en: "Wage thresholds for LMIAs received {range}: {low} an hour ({low_prov}) to {high} ({high_prov}).",
    fr: "Seuils salariaux pour les EIMT reçues {range} : de {low} l'heure ({low_prov}) à {high} ({high_prov}).",
  },
  "program.now_times": {
    en: "Average processing time in {month}: {low} business days ({low_stream}) to {high} ({high_stream}).",
    fr: "Délai de traitement moyen en {month} : de {low} jours ouvrables ({low_stream}) à {high} ({high_stream}).",
  },
  "program.cma_none": { en: "No list read is in force on {date}.", fr: "Aucune liste relevée n'est en vigueur le {date}." },
  "program.wage_none": { en: "No thresholds read are in force on {date}.", fr: "Aucun seuil relevé n'est en vigueur le {date}." },
  "program.not_read": { en: "Not read yet.", fr: "Pas encore relevé." },
  "program.times_title": { en: "LMIA Processing Times by Stream", fr: "Délais de traitement des EIMT par volet" },
  "program.times_text": {
    en: "The average number of business days Service Canada took to assess an application and render a decision once all required information was received, for the LMIAs processed in the month; ESDC updates the table monthly, about five weeks after the month begins. The times do not include the minimum advertising period an employer must complete before applying (14 days to 8 weeks, depending on the stream).",
    fr: "Le nombre moyen de jours ouvrables qu'il a fallu à Service Canada pour évaluer une demande et rendre une décision une fois toute l'information requise reçue, pour les EIMT traitées pendant le mois; EDSC met le tableau à jour chaque mois, environ cinq semaines après le début du mois. Ces délais ne comprennent pas la période minimale d'affichage qu'un employeur doit terminer avant de présenter une demande (de 14 jours à 8 semaines, selon le volet).",
  },
  "program.times_caption": { en: "Average business days, {month}", fr: "Jours ouvrables en moyenne, {month}" },
  "program.col_stream": { en: "Stream", fr: "Volet" },
  "program.col_days": { en: "Business days", fr: "Jours ouvrables" },
  "program.col_month": { en: "Month", fr: "Mois" },
  "program.history_times": { en: "All Months Read", fr: "Tous les mois relevés" },
  "program.col_read": { en: "Read", fr: "Relevé le" },
  "program.col_published": { en: "Page updated", fr: "Page mise à jour" },
  "program.col_status": { en: "Status", fr: "État" },
  "program.in_force": { en: "In force", fr: "En vigueur" },
  "program.upcoming": { en: "Upcoming", fr: "À venir" },
  "program.latest": { en: "Latest", fr: "Le plus récent" },
  "program.cma_title": {
    en: "Census Metropolitan Areas Where Low-Wage LMIAs Are Not Processed",
    fr: "Régions métropolitaines de recensement où les EIMT à bas salaire ne sont pas traitées",
  },
  "program.cma_text": {
    en: "Since 2024-09-26 ESDC does not process an LMIA application for a position paid below the provincial or territorial wage threshold when the work location is in a census metropolitan area whose unemployment rate is at or above the cut-off on the list in force when the application is submitted, outside the exempt sectors and positions the page lists. The rates are Statistics Canada's Labour Force Survey figures, and ESDC replaces the list every three months.",
    fr: "Depuis le 2024-09-26, EDSC ne traite pas une demande d'EIMT pour un poste payé sous le seuil salarial de la province ou du territoire lorsque le lieu de travail se trouve dans une région métropolitaine de recensement dont le taux de chômage atteint le seuil de la liste en vigueur au moment de la demande, sauf pour les secteurs et les postes exemptés que la page énumère. Les taux sont ceux de l'Enquête sur la population active de Statistique Canada, et EDSC remplace la liste tous les trois mois.",
  },
  "program.cma_current": {
    en: "List in force for applications submitted {range}: {n} of {total} areas at {threshold} percent or more.",
    fr: "Liste en vigueur pour les demandes soumises {range} : {n} des {total} régions à {threshold} % ou plus.",
  },
  "program.col_cma": { en: "Census metropolitan area", fr: "Région métropolitaine de recensement" },
  "program.col_rate": { en: "Unemployment rate (%)", fr: "Taux de chômage (%)" },
  "program.history_cma": { en: "All Lists Read", fr: "Toutes les listes relevées" },
  "program.col_in_force": { en: "In force", fr: "En vigueur" },
  "program.col_areas": { en: "Areas at or above the cut-off", fr: "Régions qui atteignent le seuil" },
  "program.col_cutoff": { en: "Cut-off (%)", fr: "Seuil (%)" },
  "program.cma_all": { en: "Every area's rate in each list read", fr: "Le taux de chaque région dans chaque liste relevée" },
  "program.cma_all_note": {
    en: "Rates at or above the list's cut-off are in bold, as on ESDC's page.",
    fr: "Les taux qui atteignent le seuil de la liste sont en gras, comme sur la page d'EDSC.",
  },
  "program.indicator_note": {
    en: "The low-wage stream indicator on employer profiles reads these lists for each quarter whose two applicable lists have been read here ({first} on) and Statistics Canada's Labour Force Survey rates for earlier quarters; the {methodology} explains the rule.",
    fr: "L'indicateur du volet des postes à bas salaire des profils d'employeurs lit ces listes pour chaque trimestre dont les deux listes applicables ont été relevées ici (à partir du {first}) et les taux de l'Enquête sur la population active de Statistique Canada pour les trimestres antérieurs; la {methodology} explique la règle.",
  },
  "program.indicator_note_lfs": {
    en: "The low-wage stream indicator on employer profiles reads Statistics Canada's Labour Force Survey rates until two of these lists cover a quarter; the {methodology} explains the rule.",
    fr: "L'indicateur du volet des postes à bas salaire des profils d'employeurs lit les taux de l'Enquête sur la population active de Statistique Canada jusqu'à ce que deux de ces listes couvrent un trimestre; la {methodology} explique la règle.",
  },
  "program.methodology_link": { en: "Methodology page", fr: "page Méthodologie" },
  "program.wage_title": {
    en: "Wage Thresholds Between the High-Wage and Low-Wage Streams",
    fr: "Seuils salariaux entre les volets des postes à haut et à bas salaire",
  },
  "program.wage_text": {
    en: "The hourly wage threshold is the province's or territory's median hourly wage plus 20 percent, from Statistics Canada's Labour Force Survey. An LMIA whose offered wage is at or above the threshold of the work location's province or territory goes in the high-wage stream; one below it goes in the low-wage stream.",
    fr: "Le seuil salarial horaire est le salaire horaire médian de la province ou du territoire majoré de 20 %, selon l'Enquête sur la population active de Statistique Canada. Une EIMT dont le salaire offert atteint le seuil de la province ou du territoire du lieu de travail relève du volet des postes à haut salaire; sous ce seuil, elle relève du volet des postes à bas salaire.",
  },
  "program.wage_current": { en: "Thresholds in force for LMIAs received {range}.", fr: "Seuils en vigueur pour les EIMT reçues {range}." },
  "program.col_province": { en: "Province or territory", fr: "Province ou territoire" },
  "program.col_from": { en: "From {date}", fr: "À compter du {date}" },
  "program.col_change": { en: "Change", fr: "Variation" },
  "program.history_wage": { en: "All Editions Read", fr: "Toutes les éditions relevées" },
  "program.money": { en: "${v}", fr: "{v} $" },
  "program.source_line": {
    en: "Source: {link}, page updated {published}; first read {read}, last checked {checked}.",
    fr: "Source : {link}, page mise à jour le {published}; premier relevé le {read}, dernière vérification le {checked}.",
  },
  "program.src_times": {
    en: "ESDC, Labour Market Impact Assessment application processing times",
    fr: "EDSC, Temps de traitement des demandes d'évaluation de l'impact sur le marché du travail",
  },
  "program.src_cma": {
    en: "ESDC, Refusal to process a Labour Market Impact Assessment application",
    fr: "EDSC, Refus de traiter une demande d'évaluation de l'impact sur le marché du travail",
  },
  "program.src_wage": {
    en: "ESDC, Hire a temporary foreign worker in a high-wage or low-wage position",
    fr: "EDSC, Embaucher un travailleur étranger temporaire pour un poste à haut salaire ou à bas salaire",
  },
  "program.sources": {
    en: "The three pages are published by Employment and Social Development Canada on canada.ca and reproduced here under the {terms} (non-commercial reproduction with attribution). This site reads them each night and keeps every edition it has read; a figure ESDC later changes is kept beside the earlier one. Licences for the rest of the site are on the {data}.",
    fr: "Les trois pages sont publiées par Emploi et Développement social Canada sur canada.ca et reproduites ici conformément aux {terms} (reproduction non commerciale avec attribution). Ce site les relève chaque nuit et conserve chaque édition relevée; un chiffre qu'EDSC modifie plus tard est conservé à côté du précédent. Les licences du reste du site figurent à la {data}.",
  },
  "program.terms_link": { en: "canada.ca terms and conditions", fr: "avis de Canada.ca" },
  "program.not_published": {
    en: "The program conditions have not been read yet.",
    fr: "Les conditions du programme n'ont pas encore été relevées.",
  },
  "program.seo_title": {
    en: "LMIA Program Conditions: Processing Times, Low-Wage Refusal List, Wage Thresholds",
    fr: "Conditions du programme des EIMT : délais de traitement, refus à bas salaire, seuils salariaux",
  },
  "program.seo_desc": {
    en: "The TFWP rules in force, read nightly from canada.ca: LMIA processing times by stream, where low-wage LMIAs are not processed, and the wage thresholds.",
    fr: "Règles du PTET en vigueur, relevées chaque nuit sur canada.ca : délais de traitement des EIMT, régions où les EIMT à bas salaire ne sont pas traitées, seuils salariaux.",
  },
  "program.stream.global_talent": { en: "Global Talent Stream", fr: "Volet des talents mondiaux" },
  "program.stream.agricultural": { en: "Agricultural stream", fr: "Volet agricole" },
  "program.stream.sawp": { en: "Seasonal Agricultural Worker Program", fr: "Programme des travailleurs agricoles saisonniers" },
  "program.stream.high_wage": { en: "High-wage stream", fr: "Volet des postes à haut salaire" },
  "program.stream.low_wage": { en: "Low-wage stream", fr: "Volet des postes à bas salaire" },
  "program.stream.permanent_resident": { en: "Permanent resident stream", fr: "Volet de résidence permanente" },
} as const satisfies Record<string, Entry>;

export type Key = keyof typeof STRINGS;
type Vars = Record<string, string | number>;

// Keys whose French is the English word on purpose: names, codes and words
// spelled the same in both languages. The completeness test holds every other
// key to a French string that differs from the English.
export const SAME_IN_BOTH: ReadonlySet<Key> = new Set<Key>([
  "site.name",
  "footer.copyright",
  "footer.corrections",
  "wage.unit.HOUR",
  "col.date",
  "col.source",
  "search.province",
  "search.pagination",
  "prov.AB",
  "prov.MB",
  "prov.NU",
  "prov.ON",
  "prov.SK",
  "prov.YT",
  "employer.type",
  "employer.active",
  "registry.bc_orgbook",
  "registry.corporations_canada",
  "methodology.toc_sources",
  "methodology.toc_exclusions",
  "methodology.toc_versions",
  "methodology.grade.probable",
  "methodology.grade.possible",
  "data.toc_api",
  "data.toc_licence",
  "data.lic.cc",
  "data.col_ok",
  "data.list.positive",
  "support.bar_total",
  "support.cents_one",
  "support.cents_many",
]);

export function allKeys(): Key[] {
  return Object.keys(STRINGS) as Key[];
}

export function rawEntry(key: Key): Entry {
  return STRINGS[key];
}

export function frTypography(s: string): string {
  return s
    .replace(/'/g, "’")
    .replace(/ ([:%$»])/g, " $1")
    .replace(/« /g, "« ")
    .replace(/\$ US/g, () => "$ US");
}

const frCache = new Map<Key, string>();

function template(lang: Lang, key: Key): string {
  const entry: Entry = STRINGS[key];
  if (lang !== "fr") return entry.en;
  let s = frCache.get(key);
  if (s === undefined) {
    s = frTypography(entry.fr);
    frCache.set(key, s);
  }
  return s;
}

function fill(s: string, vars?: Vars): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(vars[name]) : m));
}

export function t(lang: Lang, key: Key, vars?: Vars): string {
  return fill(template(lang, key), vars);
}

// Like t(), but a slot can hold markup (a link inside a sentence). Returns the
// pieces in order for JSX to render as children.
export function tj(lang: Lang, key: Key, slots: Record<string, unknown>): unknown[] {
  const s = template(lang, key);
  const out: unknown[] = [];
  let last = 0;
  for (const m of s.matchAll(/\{(\w+)\}/g)) {
    const at = m.index ?? 0;
    if (at > last) out.push(s.slice(last, at));
    out.push(m[1] in slots ? slots[m[1]] : m[0]);
    last = at + m[0].length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}

// English takes the singular for 1 only; French for 0 and 1.
export function tn(lang: Lang, one: Key, many: Key, n: number, vars?: Vars): string {
  const singular = lang === "fr" ? Math.abs(n) < 2 : n === 1;
  return t(lang, singular ? one : many, vars);
}

export function langFrom(query: string | undefined, cookie: string | undefined): Lang {
  if (query === "fr" || query === "en") return query;
  return cookie === "fr" ? "fr" : "en";
}

export function numberLocale(lang: Lang): string {
  return lang === "fr" ? "fr-CA" : "en-CA";
}

// A decimal written the way the language writes it ("2.9" or "2,9").
export function decimal(lang: Lang, text: string): string {
  return lang === "fr" ? text.replace(".", ",") : text;
}

// The strings a client script needs, for the page's JSON block.
export function clientStrings(lang: Lang, keys: readonly Key[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const k of keys) out[k] = template(lang, k);
  return out;
}

// -- names keyed by code ---------------------------------------------------------

const PROVINCE_KEY: Record<string, Key> = {
  AB: "prov.AB", BC: "prov.BC", MB: "prov.MB", NB: "prov.NB", NL: "prov.NL", NS: "prov.NS", NT: "prov.NT",
  NU: "prov.NU", ON: "prov.ON", PE: "prov.PE", QC: "prov.QC", SK: "prov.SK", YT: "prov.YT", XX: "prov.XX",
};

export function provinceName(lang: Lang, code: string): string {
  const key = PROVINCE_KEY[code];
  return key ? t(lang, key) : code;
}

// ESDC's stream names as they appear in the data (and in search URLs).
const STREAM_KEY: Record<string, Key> = {
  "High Wage": "stream.high_wage",
  "Low Wage": "stream.low_wage",
  "Primary Agriculture": "stream.primary_agriculture",
  "Global Talent Stream": "stream.global_talent",
  "Permanent Resident Only": "stream.permanent_resident",
};

export function streamLabel(lang: Lang, stream: string): string {
  const key = STREAM_KEY[stream];
  return key ? t(lang, key) : stream;
}

const INDICATOR_KEY: Record<string, Key> = {
  newly_incorporated: "ind.newly_incorporated",
  repeat_applicant: "ind.repeat_applicant",
  wage_at_floor: "ind.wage_at_floor",
  low_wage_high_unemployment: "ind.low_wage_high_unemployment",
  high_volume: "ind.high_volume",
  refused_then_reposted: "ind.refused_then_reposted",
};

export function indicatorLabel(lang: Lang, id: string): string {
  const key = INDICATOR_KEY[id];
  return key ? t(lang, key) : id;
}

const INDICATOR_STATE_KEY: Record<string, Key> = {
  triggered: "ind_state.triggered",
  not_triggered: "ind_state.not_triggered",
  not_applicable: "ind_state.not_applicable",
  not_evaluated: "ind_state.not_evaluated",
};

export function indicatorStateLabel(lang: Lang, state: string): string {
  const key = INDICATOR_STATE_KEY[state];
  return key ? t(lang, key) : state;
}

// -- formats ---------------------------------------------------------------------

export function periodLabel(period: string, lang: Lang = "en"): string {
  const m = /^(\d{4})Q(\d)(?:-Q(\d))?$/.exec(period);
  if (!m) return period;
  return m[3] ? t(lang, "period.range", { y: m[1], q: m[2], q2: m[3] }) : t(lang, "period.quarter", { y: m[1], q: m[2] });
}

// One formatter per language, made on first use: toLocaleString builds a new
// one on every call, which on a long profile page (hundreds of numbers) was a
// measurable share of the request's CPU time. The output is the same.
const INT_FORMAT: Partial<Record<Lang, Intl.NumberFormat>> = {};

export function fmtInt(n: number | string | null | undefined, lang: Lang = "en"): string {
  if (n === null || n === undefined || n === "") return "0";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return String(n);
  const format = (INT_FORMAT[lang] ??= new Intl.NumberFormat(numberLocale(lang)));
  return format.format(v);
}

export function fmtWage(min: number | null, max: number | null, unit: string | null, lang: Lang = "en"): string {
  if (min === null && max === null) return t(lang, "common.na");
  const unitKey = unit ? (`wage.unit.${unit}` as Key) : null;
  const u = !unit ? "" : unitKey && unitKey in STRINGS ? t(lang, unitKey) : ` ${unit.toLowerCase()}`;
  const a = min !== null ? decimal(lang, min.toFixed(2)) : null;
  const b = max !== null ? decimal(lang, max.toFixed(2)) : null;
  if (a && b && a !== b) return t(lang, "wage.range", { min: a, max: b, unit: u });
  return t(lang, "wage.single", { amount: a ?? b ?? "", unit: u });
}

// -- indicator basis -------------------------------------------------------------

const BASIS_KEYS: readonly Key[] = (Object.keys(STRINGS) as Key[]).filter((k) => k.startsWith("basis."));

function basisPattern(english: string): RegExp {
  const escaped = english.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  return new RegExp(`^${escaped.replace(/\{(\w+)\}/g, (_m, name: string) => `(?<${name}>.+?)`)}$`);
}

const BASIS_PATTERNS: { key: Key; re: RegExp }[] = BASIS_KEYS.map((key) => ({ key, re: basisPattern(STRINGS[key].en) }));

// Quarters become "T1 2026" wherever they appear; counts and amounts are
// grouped and decimals take a comma, but a code (the NOC, a posting ID) is
// left as written.
const BASIS_NUMBERS = new Set(["days", "top", "n", "run", "median", "posted", "rate", "rate2", "lists", "lfs"]);
const BASIS_UNITS: Record<string, string> = { h: "h", yr: "an" };

// Statistics Canada's French names for the economic regions and census
// metropolitan areas whose English name differs. The rest are the same.
const PLACE_FR: Record<string, string> = {
  "South Coast--Burin Peninsula": "Côte-sud--Burin Peninsula",
  "West Coast--Northern Peninsula--Labrador": "Côte-ouest--Northern Peninsula--Labrador",
  "Prince Edward Island": "Île-du-Prince-Édouard",
  "North Shore": "Côte-nord",
  Southern: "Sud",
  Northeast: "Nord-est",
  Northwest: "Nord-ouest",
  Southeast: "Sud-est",
  "South Central": "Centre sud",
  Southwest: "Sud-ouest",
  "North Central": "Centre nord",
  North: "Nord",
  Northern: "Nord",
  "Vancouver Island and Coast": "Île de Vancouver et la côte",
  "Lower Mainland--Southwest": "Lower Mainland--Sud-ouest",
  "North Coast": "Côte-nord",
  "Northwest Territories": "Territoires du Nord-Ouest",
  "Greater Sudbury": "Grand Sudbury",
};

// A census metropolitan area's name in the reader's language.
export function cmaName(lang: Lang, english: string): string {
  return lang === "fr" ? PLACE_FR[english] ?? english : english;
}

function frProvince(english: string): string {
  const code = Object.keys(PROVINCE_KEY).find((c) => STRINGS[PROVINCE_KEY[c]].en === english);
  return code ? t("fr", PROVINCE_KEY[code]) : english;
}

// The three area forms the wage indicator writes.
function frArea(v: string): string {
  const region = /^the (.+) economic region \((.+)\)$/.exec(v);
  if (region) return `région économique ${PLACE_FR[region[1]] ?? region[1]}, ${frProvince(region[2])}`;
  const province = /^(.+) \(provincial figure\)$/.exec(v);
  if (province) return `${frProvince(province[1])}, chiffre provincial`;
  if (v === "Canada (national figure)") return "Canada, chiffre national";
  return v;
}

function frValue(name: string, v: string): string {
  if (/^\d{4}Q\d(?:-Q\d)?$/.test(v)) return periodLabel(v, "fr");
  if (name === "unit" || name === "unit2") return BASIS_UNITS[v] ?? v;
  if (name === "area") return frArea(v);
  if (name === "cma") return PLACE_FR[v] ?? v;
  if (!BASIS_NUMBERS.has(name)) return v;
  if (/^\d+$/.test(v)) return fmtInt(Number(v), "fr");
  if (/^\d{1,3}(,\d{3})+$/.test(v)) return fmtInt(Number(v.replace(/,/g, "")), "fr");
  if (/^\d+\.\d+$/.test(v)) return decimal("fr", v);
  return v;
}

// The basis sentence in the reader's language. English, and any sentence the
// patterns do not know, come back unchanged with translated: false.
export function basisText(lang: Lang, basis: string): { text: string; translated: boolean } {
  if (lang !== "fr") return { text: basis, translated: true };
  for (const { key, re } of BASIS_PATTERNS) {
    const m = re.exec(basis);
    if (!m) continue;
    const vars: Vars = {};
    for (const [name, value] of Object.entries(m.groups ?? {})) vars[name] = frValue(name, value);
    return { text: t("fr", key, vars), translated: true };
  }
  return { text: basis, translated: false };
}

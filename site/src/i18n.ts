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
  "nav.methodology": { en: "Methodology", fr: "Méthodologie" },
  "nav.data": { en: "Data & About", fr: "Données et à propos" },
  "nav.support": { en: "Support", fr: "Soutenir" },
  "nav.lang": { en: "FR", fr: "EN" },
  "nav.dark": { en: "Dark", fr: "Sombre" },
  "nav.light": { en: "Light", fr: "Clair" },
  "nav.data_as_of": { en: "Data as of", fr: "Données au" },
  "footer.sources": {
    en: "Sources: Job Bank (ESDC); TFWP positive and negative LMIA employer lists (Open Government Licence, Canada); IRCC non-compliant employers; BC Registry.",
    fr: "Sources : Guichet-Emplois (EDSC); listes des employeurs ayant reçu une EIMT positive ou négative du PTET (Licence du gouvernement ouvert, Canada); employeurs jugés non conformes (IRCC); BC Registry (registre des entreprises de la Colombie-Britannique).",
  },
  "footer.download": { en: "Download the Data", fr: "Télécharger les données" },
  "footer.corrections": { en: "Corrections", fr: "Corrections" },
  "footer.support": { en: "Support the Site", fr: "Soutenir le site" },
  "footer.x": { en: "LMIA Watch on X", fr: "LMIA Watch sur X" },
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
    en: "No registry match yet. Federal corporations are matched by name; BC employers are also checked in the BC Registry.",
    fr: "Aucune correspondance au registre pour l'instant. Les sociétés fédérales sont jumelées par leur nom; les employeurs de la Colombie-Britannique sont aussi vérifiés dans le BC Registry.",
  },
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
  "employer.map_aria": { en: "Map placeholder at the postal-area centroid", fr: "Emplacement de la carte au centre du secteur postal" },
  "employer.map_text": { en: "Map at postal-area centroid", fr: "Carte au centre du secteur postal" },
  "employer.nearby": { en: "Other Employers Nearby", fr: "Autres employeurs à proximité" },
  "employer.summary": { en: "Summary", fr: "Résumé" },
  "employer.pending_postings": { en: "Pending postings", fr: "Offres en attente" },
  "employer.positions_requested": { en: "Positions requested", fr: "Postes demandés" },
  "employer.approved_lmias": { en: "Approved LMIAs", fr: "EIMT approuvées" },
  "employer.refused_lmias": { en: "Refused LMIAs", fr: "EIMT refusées" },
  "employer.positions_paren_one": { en: "({n} positions)", fr: "({n} poste)" },
  "employer.positions_paren_many": { en: "({n} positions)", fr: "({n} postes)" },
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
  "registry.bc_orgbook": { en: "BC Registry (OrgBook)", fr: "BC Registry (OrgBook)" },
  "registry.corporations_canada": { en: "Corporations Canada", fr: "Corporations Canada" },

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
    en: "BC Registry via OrgBook; Corporations Canada's open-data extract of federal corporations",
    fr: "BC Registry au moyen d'OrgBook; extrait des données ouvertes de Corporations Canada sur les sociétés fédérales",
  },
  "methodology.sources.registry.fields": {
    en: "Legal name, registration number, entity type, status, registration date",
    fr: "Dénomination sociale, numéro d'enregistrement, type d'entité, statut, date d'enregistrement",
  },
  "methodology.sources.registry.cadence": {
    en: "Nightly for new BC employers; the federal extract is refreshed weekly",
    fr: "Chaque nuit pour les nouveaux employeurs de la Colombie-Britannique; l'extrait fédéral est actualisé chaque semaine",
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
    en: "A positive-list row from 2025 Q1 on is in the Low Wage stream, and its census metropolitan area's unemployment rate was 6 percent or higher in both three-month periods that could have applied: the one in force when the decision quarter began and the one before it. Since 2024-09-26 ESDC refuses to process low-wage applications in such areas outside exempt positions",
    fr: "Une inscription sur la liste positive depuis le T1 2025 relève du volet des postes à bas salaire, et le taux de chômage de sa région métropolitaine de recensement était d'au moins 6 % pendant les deux périodes de trois mois qui pouvaient s'appliquer : celle en vigueur au début du trimestre de la décision et la précédente. Depuis le 2024-09-26, EDSC refuse de traiter les demandes à bas salaire dans ces régions, sauf pour les postes exemptés",
  },
  "methodology.ind.low_wage_high_unemployment.data": {
    en: "ESDC positive lists, Statistics Canada Labour Force Survey, 2021 Census boundaries",
    fr: "Listes positives d'EDSC, Enquête sur la population active de Statistique Canada, limites du Recensement de 2021",
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
    en: "Names are normalized before comparison: case folded, punctuation removed, legal suffixes stripped (Ltd., Inc., Corp., ULC, Limited Partnership), and accents preserved.",
    fr: "Les noms sont normalisés avant la comparaison : casse uniformisée, ponctuation retirée, suffixes juridiques supprimés (Ltd., Inc., Corp., ULC, Limited Partnership) et accents conservés.",
  },
  "methodology.col_grade": { en: "Grade", fr: "Niveau" },
  "methodology.col_condition": { en: "Condition", fr: "Critère" },
  "methodology.col_shown_as": { en: "Shown as", fr: "Présentation" },
  "methodology.grade.exact": { en: "Exact", fr: "Exacte" },
  "methodology.grade.exact.condition": { en: "Normalized name and full postal code agree", fr: "Le nom normalisé et le code postal complet concordent" },
  "methodology.grade.exact.shown": { en: "Merged into one profile", fr: "Regroupés dans un seul profil" },
  "methodology.grade.probable": { en: "Probable", fr: "Probable" },
  "methodology.grade.probable.condition": {
    en: "Normalized name and city agree, or name only where the posting uses a trade name",
    fr: "Le nom normalisé et la ville concordent, ou le nom seul lorsque l'offre utilise un nom commercial",
  },
  "methodology.grade.probable.shown": {
    en: 'Merged, with "Probable" on the registry card and both raw strings visible',
    fr: "Regroupés, avec « Probable » sur la fiche du registre et les deux chaînes brutes visibles",
  },
  "methodology.grade.possible": { en: "Possible", fr: "Possible" },
  "methodology.grade.possible.condition": { en: "Name similarity above a threshold, different city", fr: "Similarité de nom au-dessus d'un seuil, ville différente" },
  "methodology.grade.possible.shown": {
    en: 'Listed as "possibly related" and kept as a separate profile',
    fr: "Indiqué comme « possiblement lié » et conservé comme profil distinct",
  },
  "methodology.grade.unmatched": { en: "Unmatched", fr: "Non jumelé" },
  "methodology.grade.unmatched.condition": { en: "Nothing above threshold", fr: "Rien au-dessus du seuil" },
  "methodology.grade.unmatched.shown": { en: "Own profile with no registry card", fr: "Profil distinct sans fiche de registre" },
  "methodology.exclusions_households": {
    en: "Private households and individuals are not published. Caregiver and home-support postings where the employer is a person are dropped before anything is stored. ESDC already removes employers with personal names from its lists, so coverage of caregiver hiring is incomplete by design.",
    fr: "Les ménages privés et les particuliers ne sont pas publiés. Les offres d'aide familiale et de soutien à domicile dont l'employeur est une personne sont écartées avant tout enregistrement. EDSC retire déjà de ses listes les employeurs portant un nom de personne : la couverture de l'embauche d'aides familiaux est donc incomplète par conception.",
  },
  "methodology.exclusions_workers": {
    en: "No worker is ever named. Applicant counts, resumes and contact details on a posting are not collected.",
    fr: "Aucun travailleur n'est jamais nommé. Le nombre de candidats, les curriculum vitæ et les coordonnées figurant sur une offre ne sont pas recueillis.",
  },
  "methodology.limits_text": {
    en: "The ESDC lists count positions on LMIAs. They do not count work permits issued or workers who arrived. The pending flag exists only for employers who advertised on Job Bank, which most streams require. Street addresses appear only when an employer entered one; the quarterly lists give a city and postal code. Registry matches are by name and can be wrong.",
    fr: "Les listes d'EDSC comptent les postes visés par des EIMT. Elles ne comptent ni les permis de travail délivrés ni les travailleurs arrivés. La mention « EIMT demandée » n'existe que pour les employeurs qui ont annoncé au Guichet-Emplois, ce que la plupart des volets exigent. Les adresses municipales ne paraissent que si l'employeur en a inscrit une; les listes trimestrielles donnent une ville et un code postal. Les correspondances au registre se fondent sur le nom et peuvent être erronées.",
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
    en: "ESDC's positive and negative LMIA employer lists and the federal corporations extract from Innovation, Science and Economic Development Canada are published under the Open Government Licence, Canada. Derived files on this site are released under the same licence. Job Bank content is Government of Canada material reproduced with attribution. Postal-area centroids come from GeoNames (CC BY 4.0).",
    fr: "Les listes des employeurs ayant reçu une EIMT positive ou négative d'EDSC et l'extrait des sociétés fédérales d'Innovation, Sciences et Développement économique Canada sont publiés sous la Licence du gouvernement ouvert, Canada. Les fichiers dérivés de ce site sont diffusés sous la même licence. Le contenu du Guichet-Emplois est du matériel du gouvernement du Canada reproduit avec attribution. Les centres des secteurs postaux proviennent de GeoNames (CC BY 4.0).",
  },
  "data.sources_text": {
    en: "The wage and unemployment indicators use {wages} (Open Government Licence, Canada), Statistics Canada's {lfs} and the {boundaries}, used under the {statcan}.",
    fr: "Les indicateurs salarial et de chômage utilisent les {wages} (Licence du gouvernement ouvert, Canada), le {lfs} de Statistique Canada et les {boundaries}, utilisés sous la {statcan}.",
  },
  "data.src.wages": { en: "Job Bank wages", fr: "salaires du Guichet-Emplois" },
  "data.src.lfs": { en: "Labour Force Survey table 14-10-0459-01", fr: "tableau 14-10-0459-01 de l'Enquête sur la population active" },
  "data.src.boundaries": { en: "2021 Census boundary files", fr: "fichiers des limites du Recensement de 2021" },
  "data.src.statcan_licence": { en: "Statistics Canada Open Licence", fr: "Licence ouverte de Statistique Canada" },
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
  "data.recomputed_wages": { en: "Wage at floor, low-wage stream", fr: "Salaire au plancher, volet des postes à bas salaire" },
  "data.runs": { en: "Recent Runs", fr: "Exécutions récentes" },
  "data.col_run": { en: "Run", fr: "Exécution" },
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
  "support.limits": { en: "Limits of the Free Tier", fr: "Limites du forfait gratuit" },
  "support.limit_views": { en: "{n} page views a day.", fr: "{n} pages vues par jour." },
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
  "support.bar_hosting": { en: "Hosting", fr: "Hébergement" },
  "support.bar_x": { en: "Daily post on X (optional)", fr: "Publication quotidienne sur X (facultatif)" },
  "support.bar_total": { en: "Total", fr: "Total" },
  "support.costs_detail": {
    en: "Domain registration is {domain} a year. Hosting (the Workers, storage, database and scheduled runs) is all on free tiers. The daily post on X is billed by X per message ({usd} without a link), about {monthly} a month. It is optional and the site runs without it.",
    fr: "L'enregistrement du domaine coûte {domain} par année. L'hébergement (les Workers, le stockage, la base de données et les exécutions planifiées) relève entièrement de forfaits gratuits. La publication quotidienne sur X est facturée par X à chaque message ({usd} sans lien), soit environ {monthly} par mois. Elle est facultative et le site fonctionne sans elle.",
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
  "support.tier.baseline.name": { en: "Baseline", fr: "Base" },
  "support.tier.baseline.unlocks": {
    en: "Keeps the site online at its own address, with hosting on free tiers, and the daily post on X.",
    fr: "Garde le site en ligne à sa propre adresse, avec un hébergement sur des forfaits gratuits, et la publication quotidienne sur X.",
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

export function fmtInt(n: number | string | null | undefined, lang: Lang = "en"): string {
  if (n === null || n === undefined || n === "") return "0";
  const v = typeof n === "string" ? Number(n) : n;
  return Number.isFinite(v) ? v.toLocaleString(numberLocale(lang)) : String(n);
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
const BASIS_NUMBERS = new Set(["days", "top", "n", "run", "median", "posted", "rate", "rate2"]);
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

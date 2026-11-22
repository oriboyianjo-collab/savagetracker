'use strict';

/** Official (and schedule-only private) event catalog. Names must match existing calendar.json rows. */

const ev = (o) => o;

const CATALOG = [
  // ---- BLS ----
  ev({
    id: 'bls-cpi-mm', agency: 'bls', country: 'US', importance: 3,
    he: 'מדד המחירים לצרכן - חודשי', en: 'Consumer price index - monthly',
    aliases: ['Consumer Price Index', 'CPI'],
    period: 'חודשי',
    blsSeries: { id: 'CUSR0000SA0', calc: 'mom' },
    blsRelease: 'https://www.bls.gov/news.release/cpi.nr0.htm',
    blsSummary: 'Consumer Price Index',
    headline: true,
  }),
  ev({
    id: 'bls-cpi-yy', agency: 'bls', country: 'US', importance: 3,
    he: 'מדד המחירים לצרכן - שנתי', en: 'Consumer price index - annual',
    aliases: ['Consumer Price Index'],
    period: 'שנתי',
    blsSeries: { id: 'CUUR0000SA0', calc: 'yoy' },
    blsRelease: 'https://www.bls.gov/news.release/cpi.nr0.htm',
    blsSummary: 'Consumer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-cpi-core-mm', agency: 'bls', country: 'US', importance: 3,
    he: 'מדד המחירים לצרכן ליבה - חודשי', en: 'Core consumer price index - monthly',
    period: 'חודשי',
    blsSeries: { id: 'CUSR0000SA0L1E', calc: 'mom' },
    blsRelease: 'https://www.bls.gov/news.release/cpi.nr0.htm',
    blsSummary: 'Consumer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-cpi-core-yy', agency: 'bls', country: 'US', importance: 3,
    he: 'מדד המחירים לצרכן ליבה - שנתי', en: 'Core consumer price index - annual',
    period: 'שנתי',
    blsSeries: { id: 'CUUR0000SA0L1E', calc: 'yoy' },
    blsRelease: 'https://www.bls.gov/news.release/cpi.nr0.htm',
    blsSummary: 'Consumer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-nfp', agency: 'bls', country: 'US', importance: 3,
    he: 'דוח תעסוקה - שכר לא-חקלאי', en: 'Employment report - nonfarm payrolls',
    aliases: ['Employment Situation', 'Nonfarm payrolls'],
    period: 'חודשי',
    blsSeries: { id: 'CES0000000001', calc: 'net', scale: 1000 }, // CES level is in thousands of jobs
    blsRelease: 'https://www.bls.gov/news.release/empsit.nr0.htm',
    blsSummary: 'Employment Situation',
    format: 'payrolls',
  }),
  ev({
    id: 'bls-unemp', agency: 'bls', country: 'US', importance: 3,
    he: 'שיעור האבטלה', en: 'Unemployment rate',
    aliases: ['Employment Situation'],
    period: 'חודשי',
    blsSeries: { id: 'LNS14000000', calc: 'level' },
    blsRelease: 'https://www.bls.gov/news.release/empsit.nr0.htm',
    blsSummary: 'Employment Situation',
    sibling: true,
    format: 'pct-level',
  }),
  ev({
    id: 'bls-ahe-mm', agency: 'bls', country: 'US', importance: 2,
    he: 'שכר שעתי ממוצע - חודשי', en: 'Average hourly earnings - monthly',
    period: 'חודשי',
    blsSeries: { id: 'CES0500000003', calc: 'mom' },
    blsRelease: 'https://www.bls.gov/news.release/empsit.nr0.htm',
    blsSummary: 'Employment Situation',
    sibling: true,
  }),
  ev({
    id: 'bls-ahe-yy', agency: 'bls', country: 'US', importance: 2,
    he: 'שכר שעתי ממוצע - שנתי', en: 'Average hourly earnings - annual',
    period: 'שנתי',
    blsSeries: { id: 'CES0500000003', calc: 'yoy' },
    blsRelease: 'https://www.bls.gov/news.release/empsit.nr0.htm',
    blsSummary: 'Employment Situation',
    sibling: true,
  }),
  ev({
    id: 'bls-ppi-mm', agency: 'bls', country: 'US', importance: 2,
    he: 'מדד המחירים ליצרן - חודשי', en: 'Producer price index - monthly',
    aliases: ['Producer Price Index'],
    period: 'חודשי',
    blsSeries: { id: 'WPSFD4', calc: 'mom' },
    blsRelease: 'https://www.bls.gov/news.release/ppi.nr0.htm',
    blsSummary: 'Producer Price Index',
  }),
  ev({
    id: 'bls-ppi-yy', agency: 'bls', country: 'US', importance: 2,
    he: 'מדד המחירים ליצרן - שנתי', en: 'Producer price index - annual',
    period: 'שנתי',
    blsSeries: { id: 'WPUFD4', calc: 'yoy' }, // BLS 12-month changes use NSA
    blsRelease: 'https://www.bls.gov/news.release/ppi.nr0.htm',
    blsSummary: 'Producer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-ppi-core-mm', agency: 'bls', country: 'US', importance: 2,
    he: 'מדד המחירים ליצרן ליבה - חודשי', en: 'Core producer price index - monthly',
    period: 'חודשי',
    blsSeries: { id: 'WPSFD49104', calc: 'mom' },
    blsRelease: 'https://www.bls.gov/news.release/ppi.nr0.htm',
    blsSummary: 'Producer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-ppi-core-yy', agency: 'bls', country: 'US', importance: 2,
    he: 'מדד המחירים ליצרן ליבה - שנתי', en: 'Core producer price index - annual',
    period: 'שנתי',
    blsSeries: { id: 'WPUFD49104', calc: 'yoy' }, // BLS 12-month changes use NSA
    blsRelease: 'https://www.bls.gov/news.release/ppi.nr0.htm',
    blsSummary: 'Producer Price Index',
    sibling: true,
  }),
  ev({
    id: 'bls-jolts', agency: 'bls', country: 'US', importance: 2,
    he: 'סקר פתיחות תעסוקה JOLTS', en: 'Job openings - JOLTS',
    aliases: ['Job Openings and Labor Turnover Survey'],
    period: 'חודשי',
    blsSeries: { id: 'JTS000000000000000JOL', calc: 'level', scale: 1000, lag: 2 }, // thousands; JOLTS reports two months back
    blsRelease: 'https://www.bls.gov/news.release/jolts.nr0.htm',
    blsSummary: 'Job Openings and Labor Turnover Survey',
    format: 'millions',
  }),
  ev({
    id: 'bls-eci', agency: 'bls', country: 'US', importance: 2,
    he: 'מדד עלות התעסוקה (ECI)', en: 'Employment Cost Index (ECI)',
    aliases: ['Employment Cost Index'],
    blsSummary: 'Employment Cost Index',
  }),
  ev({
    id: 'bls-import-mm', agency: 'bls', country: 'US', importance: 1,
    he: 'מדד מחירי יבוא - חודשי', en: 'Import price index - monthly',
    aliases: ['U.S. Import and Export Price Indexes'],
    period: 'חודשי',
    blsSeries: { id: 'EIUIR', calc: 'mom', signed: true },
    blsRelease: 'https://www.bls.gov/news.release/ximpim.nr0.htm',
    blsSummary: 'U.S. Import and Export Price Indexes',
  }),
  ev({
    id: 'bls-import-yy', agency: 'bls', country: 'US', importance: 1,
    he: 'מדד מחירי יבוא - שנתי', en: 'Import price index - annual',
    period: 'שנתי',
    blsSeries: { id: 'EIUIR', calc: 'yoy', signed: true },
    blsRelease: 'https://www.bls.gov/news.release/ximpim.nr0.htm',
    blsSummary: 'U.S. Import and Export Price Indexes',
    sibling: true,
  }),
  ev({
    id: 'bls-export-mm', agency: 'bls', country: 'US', importance: 1,
    he: 'מדד מחירי יצוא - חודשי', en: 'Export price index - monthly',
    period: 'חודשי',
    blsSeries: { id: 'EIUIQ', calc: 'mom', signed: true },
    blsRelease: 'https://www.bls.gov/news.release/ximpim.nr0.htm',
    blsSummary: 'U.S. Import and Export Price Indexes',
    sibling: true,
  }),
  ev({
    id: 'bls-export-yy', agency: 'bls', country: 'US', importance: 1,
    he: 'מדד מחירי יצוא - שנתי', en: 'Export price index - annual',
    period: 'שנתי',
    blsSeries: { id: 'EIUIQ', calc: 'yoy', signed: true },
    blsRelease: 'https://www.bls.gov/news.release/ximpim.nr0.htm',
    blsSummary: 'U.S. Import and Export Price Indexes',
    sibling: true,
  }),
  ev({
    id: 'bls-productivity', agency: 'bls', country: 'US', importance: 1,
    he: 'פרודוקטיביות לא-חקלאית - מקדמי', en: 'Nonfarm productivity - preliminary',
    aliases: ['Productivity and Costs'],
    blsSummary: 'Productivity and Costs',
  }),
  ev({
    id: 'bls-unit-labor', agency: 'bls', country: 'US', importance: 1,
    he: 'עלויות יחידת עבודה - מקדמי', en: 'Unit labor costs - preliminary',
    aliases: ['Productivity and Costs'],
    blsSummary: 'Productivity and Costs',
    sibling: true,
  }),
  ev({
    id: 'bls-real-earnings', agency: 'bls', country: 'US', importance: 1,
    he: 'שכר ריאלי', en: 'Real earnings',
    aliases: ['Real Earnings'],
    blsSummary: 'Real Earnings',
  }),
  ev({
    id: 'bls-injuries', agency: 'bls', country: 'US', importance: 1,
    he: 'פציעות ומחלות במקום העבודה לפי דיווחי מעסיקים', en: 'Employer-reported workplace injuries and illnesses',
    aliases: ['Employer-Reported Workplace Injuries and Illnesses (Annual)'],
    blsSummary: 'Employer-Reported Workplace Injuries and Illnesses (Annual)',
    scheduleOnly: false,
  }),
  ev({
    id: 'bls-state-emp', agency: 'bls', country: 'US', importance: 1,
    he: 'תעסוקה ואבטלה לפי מדינה בארה"ב', en: 'State employment and unemployment',
    aliases: ['State Employment and Unemployment (Monthly)'],
    blsSummary: 'State Employment and Unemployment (Monthly)',
  }),
  ev({
    id: 'bls-mfp', agency: 'bls', country: 'US', importance: 1,
    he: 'פריון כלל גורמי הייצור בענפים עיקריים', en: 'Multifactor productivity in major industries',
    aliases: ['Multifactor Productivity', 'Total factor productivity'],
  }),

  // ---- BEA ----
  ev({
    id: 'bea-gdp-adv', agency: 'bea', country: 'US', importance: 3,
    he: 'תמ"ג ריאלי (הערכה ראשונה)', en: 'Real GDP (advance estimate)',
    aliases: ['GDP (Advance Estimate)', 'Gross Domestic Product'],
  }),
  ev({
    id: 'bea-gdp-2nd', agency: 'bea', country: 'US', importance: 3,
    he: 'תמ"ג ריאלי (הערכה שנייה)', en: 'Real GDP (second estimate)',
    aliases: ['GDP (Second Estimate) and Corporate Profits'],
  }),
  ev({
    id: 'bea-gdp-3rd', agency: 'bea', country: 'US', importance: 3,
    he: 'תמ"ג ריאלי (הערכה שלישית)', en: 'Real GDP (third estimate)',
    aliases: ['GDP (Third Estimate)'],
  }),
  ev({
    id: 'bea-pce-mm', agency: 'bea', country: 'US', importance: 2,
    he: 'מדד PCE כללי - חודשי (m/m)', en: 'Headline PCE index - monthly (m/m)',
    aliases: ['Personal Income and Outlays'],
  }),
  ev({
    id: 'bea-pce-yy', agency: 'bea', country: 'US', importance: 2,
    he: 'מדד PCE כללי - שנתי (y/y)', en: 'Headline PCE index - annual (y/y)',
    aliases: ['Personal Income and Outlays'],
    sibling: true,
  }),
  ev({
    id: 'bea-pce-core-mm', agency: 'bea', country: 'US', importance: 3,
    he: 'מדד PCE ליבה - חודשי (m/m)', en: 'Core PCE index - monthly (m/m)',
    aliases: ['Personal Income and Outlays'],
    sibling: true,
  }),
  ev({
    id: 'bea-pce-core-yy', agency: 'bea', country: 'US', importance: 3,
    he: 'מדד PCE ליבה - שנתי (y/y)', en: 'Core PCE index - annual (y/y)',
    aliases: ['Personal Income and Outlays'],
    sibling: true,
  }),
  ev({
    id: 'bea-income', agency: 'bea', country: 'US', importance: 2,
    he: 'הכנסה אישית', en: 'Personal income',
    aliases: ['Personal Income and Outlays'],
    sibling: true,
  }),
  ev({
    id: 'bea-spending', agency: 'bea', country: 'US', importance: 2,
    he: 'הוצאות צרכניות (PCE נומינלי)', en: 'Consumer spending (nominal PCE)',
    aliases: ['Personal Income and Outlays'],
    sibling: true,
  }),
  ev({
    id: 'bea-outdoor', agency: 'bea', country: 'US', importance: 1,
    he: 'נתוני כלכלת הפנאי בטבע - ארה"ב והמדינות', en: 'Outdoor recreation economic statistics - U.S. and states',
    aliases: ['Outdoor Recreation Economic Statistics, U.S. and States, 2025', 'Outdoor Recreation Economic Statistics'],
  }),
  ev({
    id: 'bea-mne', agency: 'bea', country: 'US', importance: 1,
    he: 'פעילות חברות רב-לאומיות אמריקאיות', en: 'Activities of U.S. multinational enterprises',
    aliases: ['Activities of U.S. Multinational Enterprises'],
  }),
  ev({
    id: 'bea-superintel', agency: 'bea', country: 'US', importance: 1,
    he: 'נתונים ניסיוניים של כלכלת בינת-על', en: 'Experimental Super Intelligence Economic Statistics',
    aliases: ['Experimental Super Intelligence Economic Statistics, 2024', 'Experimental Super Intelligence Economic Statistics'],
  }),
  ev({
    id: 'bea-profits', agency: 'bea', country: 'US', importance: 2,
    he: 'רווחי חברות (הערכה שנייה)', en: 'Corporate profits (second estimate)',
    aliases: ['GDP (Second Estimate) and Corporate Profits'],
    sibling: true,
  }),

  // ---- Census ----
  ev({
    id: 'census-housing-starts', agency: 'census', country: 'US', importance: 2,
    he: 'בנייה למגורים חדשה - התחלות בנייה והיתרים', en: 'New residential construction - housing starts and permits',
    aliases: ['New Residential Construction (Building Permits, Housing Starts, and Housing Completions)', 'Housing starts'],
  }),
  ev({
    id: 'census-retail-mm', agency: 'census', country: 'US', importance: 1,
    he: 'מכירות קמעונאיות - חודשי', en: 'Retail sales - monthly',
    aliases: ['Advance Monthly Sales for Retail and Food Services'],
  }),
  ev({
    id: 'census-retail-yy', agency: 'census', country: 'US', importance: 1,
    he: 'מכירות קמעונאיות - שנתי', en: 'Retail sales - annual',
    aliases: ['Advance Monthly Sales for Retail and Food Services'],
    sibling: true,
  }),
  ev({
    id: 'census-durables', agency: 'census', country: 'US', importance: 2,
    he: 'הזמנות למוצרי בני קיימא (כולל תחבורה)', en: 'Durable goods orders (incl. transportation)',
    aliases: ["Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders", 'Durable goods'],
  }),
  ev({
    id: 'census-durables-core', agency: 'census', country: 'US', importance: 2,
    he: 'הזמנות למוצרי בני קיימא ללא תחבורה (ליבה)', en: 'Durable goods orders ex-transportation (core)',
    aliases: ["Advance Report on Durable Goods--Manufacturers' Shipments, Inventories, and Orders"],
    sibling: true,
  }),
  ev({
    id: 'census-new-home', agency: 'census', country: 'US', importance: 1,
    he: 'מכירות בתים חדשים', en: 'New home sales',
    aliases: ['New Residential Sales'],
  }),
  ev({
    id: 'census-adv-services', agency: 'census', country: 'US', importance: 1,
    he: 'דוח מקדים על ענפי השירותים', en: 'Advance Services Report',
    aliases: ['Advance Services Report'],
  }),
  ev({
    id: 'census-adv-indicators', agency: 'census', country: 'US', importance: 1,
    he: 'מאזן הסחורות (מוקדם)', en: 'Goods trade balance (advance)',
    aliases: ['Advance Economic Indicators Report (International Trade, Retail, & Wholesale)'],
  }),
  ev({
    id: 'census-factory', agency: 'census', country: 'US', importance: 1,
    he: 'הזמנות מפעלים', en: 'Factory orders',
    aliases: ["Full Report - Manufacturers' Shipments, Inventories and Orders"],
  }),
  ev({
    id: 'census-construction', agency: 'census', country: 'US', importance: 1,
    he: 'הוצאות בנייה', en: 'Construction spending',
    aliases: ['Construction Spending (Construction Put in Place)'],
  }),
  ev({
    id: 'census-wholesale', agency: 'census', country: 'US', importance: 1,
    he: 'מלאי סיטונאות (מוקדם)', en: 'Wholesale inventories (advance)',
    aliases: ['Monthly Wholesale Trade: Sales and Inventories'],
  }),
  ev({
    id: 'census-business-inv', agency: 'census', country: 'US', importance: 1,
    he: 'מלאי עסקים - חודשי', en: 'Business inventories - monthly',
    aliases: ['Manufacturing and Trade: Inventories and Sales'],
  }),
  ev({
    id: 'census-bfs', agency: 'census', country: 'US', importance: 1,
    he: 'בקשות לעסקים / הקמות מעסיקות חזויות - Census', en: 'Business applications / projected employer formations - Census',
    aliases: ['Business Formation Statistics'],
  }),
  ev({
    id: 'census-trade', agency: 'census', country: 'US', importance: 2,
    he: 'מאזן הסחר (סחורות ושירותים)', en: 'Trade balance (goods and services)',
    aliases: ['U.S. International Trade in Goods and Services'],
  }),

  // ---- DOL ----
  ev({
    id: 'dol-claims', agency: 'dol', country: 'US', importance: 2,
    he: 'תביעות אבטלה שבועיות', en: 'Weekly jobless claims',
    aliases: ['Unemployment Insurance Weekly Claims', 'Initial claims'],
    format: 'claims',
  }),
  ev({
    id: 'dol-claims-cont', agency: 'dol', country: 'US', importance: 1,
    he: 'תביעות אבטלה מתמשכות', en: 'Continuing jobless claims',
    aliases: ['Unemployment Insurance Weekly Claims', 'Continued claims'],
    format: 'claims-cont',
    sibling: true,
  }),

  // ---- EIA ----
  ev({
    id: 'eia-crude', agency: 'eia', country: 'US', importance: 1,
    he: 'מלאי נפט גולמי שבועי (EIA)', en: 'Weekly crude oil inventories (EIA)',
    aliases: ['Weekly Petroleum Status Report', 'Crude oil inventories'],
  }),
  ev({
    id: 'eia-gas', agency: 'eia', country: 'US', importance: 1,
    he: 'מלאי גז טבעי שבועי (EIA)', en: 'Weekly natural gas inventories (EIA)',
    aliases: ['Weekly Natural Gas Storage Report'],
  }),
  ev({
    id: 'eia-gasdiesel', agency: 'eia', country: 'US', importance: 1,
    he: 'עדכון מחירי בנזין וסולר שבועי (EIA)', en: 'Weekly gasoline and diesel price update (EIA)',
  }),
  ev({
    id: 'eia-coal', agency: 'eia', country: 'US', importance: 1,
    he: 'סקירת שוק הפחם השבועית (EIA)', en: 'Weekly coal market review (EIA)',
  }),

  // ---- Fed Board statistical releases ----
  ev({
    id: 'fed-h15', agency: 'fed', country: 'US', importance: 1,
    he: 'ריביות נבחרות (H.15) - הפד', en: 'Selected interest rates (H.15) - Fed',
    aliases: ['H.15', 'Selected Interest Rates'],
    publishedStyle: true,
  }),
  ev({
    id: 'fed-cp', agency: 'fed', country: 'US', importance: 1,
    he: 'נתוני ניירות ערך מסחריים (CP) - הפד', en: 'Commercial paper (CP) data - Fed',
    aliases: ['Commercial Paper'],
    publishedStyle: true,
  }),
  ev({
    id: 'fed-h41', agency: 'fed', country: 'US', importance: 1,
    he: 'מאזן הפד וגורמי יתרות (H.4.1)', en: 'Fed balance sheet and reserve factors (H.4.1)',
    aliases: ['H.4.1', 'Factors Affecting Reserve Balances'],
    publishedStyle: true,
  }),
  ev({
    id: 'fed-h8', agency: 'fed', country: 'US', importance: 1,
    he: 'נכסים והתחייבויות בנקים מסחריים (H.8)', en: 'Assets and liabilities of commercial banks (H.8)',
    aliases: ['H.8'],
    publishedStyle: true,
  }),
  ev({
    id: 'fed-h10', agency: 'fed', country: 'US', importance: 1,
    he: 'שערי חליפין שבועיים (H.10) - הפד', en: 'Weekly foreign exchange rates (H.10) - Fed',
    aliases: ['H.10'],
    publishedStyle: true,
  }),
  ev({
    id: 'fed-g17-ip', agency: 'fed', country: 'US', importance: 1,
    he: 'ייצור תעשייתי - חודשי', en: 'Industrial production - monthly',
    aliases: ['G.17', 'Industrial Production and Capacity Utilization'],
  }),
  ev({
    id: 'fed-g17-cu', agency: 'fed', country: 'US', importance: 1,
    he: 'ניצולת כושר ייצור', en: 'Capacity utilization',
    aliases: ['G.17', 'Industrial Production and Capacity Utilization'],
    sibling: true,
  }),
  ev({
    id: 'fed-g19', agency: 'fed', country: 'US', importance: 1,
    he: 'אשראי צרכני', en: 'Consumer credit',
    aliases: ['G.19', 'Consumer Credit'],
  }),
  ev({
    id: 'fed-fomc', agency: 'fed', country: 'US', importance: 3,
    he: 'החלטת הריבית של הפד (FOMC)', en: 'FOMC interest rate decision',
    aliases: ['FOMC', 'Federal Open Market Committee'],
  }),
  ev({
    id: 'fed-fomc-minutes', agency: 'fed', country: 'US', importance: 3,
    he: 'פרסום פרוטוקול ישיבת FOMC', en: 'Release of FOMC meeting minutes',
    aliases: ['Minutes of the Federal Open Market Committee', 'FOMC Minutes'],
    publishedStyle: true,
  }),

  // ---- Treasury ----
  ev({
    id: 'treas-mts', agency: 'treasury', country: 'US', importance: 1,
    he: 'מאזן תקציב ממשלתי חודשי (Monthly Treasury Statement)', en: 'Monthly federal budget statement (Monthly Treasury Statement)',
    aliases: ['Monthly Treasury Statement'],
  }),

  // ---- FHFA ----
  ev({
    id: 'fhfa-hpi', agency: 'fhfa', country: 'US', importance: 1,
    he: 'מדד מחירי הבתים (FHFA)', en: 'House Price Index (FHFA)',
    aliases: ['FHFA House Price Index'],
  }),

  // ---- Regional Fed research (official) ----
  ev({
    id: 'nyfed-nowcast', agency: 'nyfed', country: 'US', importance: 1,
    he: 'אומדן צמיחה - New York Fed Staff Nowcast', en: 'Growth estimate - New York Fed Staff Nowcast',
  }),
  ev({
    id: 'nyfed-empire', agency: 'nyfed', country: 'US', importance: 2,
    he: 'סקר הייצור של האמפייר סטייט', en: 'Empire State Manufacturing Survey',
    aliases: ['Empire State Manufacturing Survey'],
  }),
  ev({
    id: 'dallas-wei', agency: 'dallasfed', country: 'US', importance: 1,
    he: 'מדד כלכלי שבועי - WEI', en: 'Weekly Economic Index - WEI',
  }),
  ev({
    id: 'philly-mbos', agency: 'phillyfed', country: 'US', importance: 1,
    he: 'סקר הייצור של הפד של פילדלפיה - MBOS', en: 'Philadelphia Fed manufacturing survey - MBOS',
    aliases: ['Manufacturing Business Outlook Survey', 'MBOS'],
  }),
  ev({
    id: 'philly-spf', agency: 'phillyfed', country: 'US', importance: 1,
    he: 'סקר החזאים המקצועיים', en: 'Survey of Professional Forecasters',
    aliases: ['Survey of Professional Forecasters'],
  }),

  // ---- Eurostat ----
  ev({
    id: 'eurostat-ip', agency: 'eurostat', country: 'EU', importance: 2,
    he: 'ייצור תעשייתי בגוש האירו - חודשי', en: 'Euro-area industrial production - monthly',
    aliases: ['Industrial production', 'Euro area industrial production'],
  }),

  // ---- Private: schedule + official link only, never numbers ----
  ev({
    id: 'umich-prelim', agency: 'umich', country: 'US', importance: 2, private: true,
    he: 'מדד סנטימנט הצרכנים של אוניברסיטת מישיגן - מקדמי', en: 'University of Michigan consumer sentiment index - preliminary',
  }),
  ev({
    id: 'umich-final', agency: 'umich', country: 'US', importance: 2, private: true,
    he: 'מדד סנטימנט הצרכנים של אוניברסיטת מישיגן - סופי', en: 'University of Michigan consumer sentiment index - final',
  }),
  ev({
    id: 'umich-inf1', agency: 'umich', country: 'US', importance: 2, private: true,
    he: 'ציפיות אינפלציה לשנה - אוניברסיטת מישיגן', en: 'Year-ahead inflation expectations - University of Michigan',
  }),
  ev({
    id: 'umich-inf-lt', agency: 'umich', country: 'US', importance: 1, private: true,
    he: 'ציפיות אינפלציה ארוכות טווח - אוניברסיטת מישיגן', en: 'Long-run inflation expectations - University of Michigan',
  }),
  ev({
    id: 'nar-pending', agency: 'nar', country: 'US', importance: 1, private: true,
    he: 'מכירות בתים בהמתנה - Pending Home Sales', en: 'Pending home sales index - NAR',
    aliases: ['Pending Home Sales'],
  }),
  ev({
    id: 'nar-existing', agency: 'nar', country: 'US', importance: 1, private: true,
    he: 'מכירות בתים קיימים', en: 'Existing home sales',
    aliases: ['Existing-Home Sales'],
  }),
];

function byId(id) { return CATALOG.find((e) => e.id === id); }

function matchSummary(summary, agency) {
  const s = String(summary || '').replace(/\\,/g, ',').trim();
  return CATALOG.filter((e) => {
    if (agency && e.agency !== agency) return false;
    if (e.blsSummary && e.blsSummary === s) return true;
    return (e.aliases || []).some((a) => s === a || s.startsWith(a + ',') || s.startsWith(a + ' '));
  });
}

module.exports = { CATALOG, byId, matchSummary };

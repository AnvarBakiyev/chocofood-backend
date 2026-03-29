from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
import random, datetime, json, time, threading, asyncio, base64
from email.mime.text import MIMEText
from pathlib import Path

try:
    import openai as _oai
    _has_openai = True
except ImportError:
    _has_openai = False

app = FastAPI(title='Chocofood Intelligence')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

ROOT   = Path(__file__).parent
DIST   = ROOT / 'dist'
STATIC = ROOT / 'static_dashboards'
PORT   = 8300
OPENAI_KEY = ''
REFRESH_SEC = 300
KV_TOKEN = '18c2e460-7620-48d1-9403-0be400a9be2a'

def rnd(b, p=5):
    return round(b * (1 + random.uniform(-p/100, p/100)))

def gen_metrics():
    return {
        'ts': datetime.datetime.now().isoformat(),
        'sr': {'mau': rnd(14200), 'mau_wow': round(random.uniform(1.5,4.8),1),
               'locations': rnd(89,2), 'locations_target': 150,
               'gmv': rnd(18500000,8), 'retention_m12': round(random.uniform(81,85),1)},
        'chocolife': {'active_12m': rnd(109000,3), 'active_wow': round(random.uniform(-2.1,0.8),1),
                      'cac': rnd(2850,8), 'clv_cac': round(random.uniform(4.8,5.4),1)},
        'chocofood': {
            'gmv_month': rnd(700000000,5), 'mau': rnd(182000,3),
            'cm_pct': round(random.uniform(-10,-8),1), 'orders_month': rnd(178000,4),
            'aov': rnd(3850,4), 'order_freq': round(random.uniform(1.8,2.1),2),
            'on_time_pct': round(random.uniform(82,87),1),
            'delivery_time': round(random.uniform(26,32),1),
            'cancel_rate': round(random.uniform(2.0,3.5),1),
            'restaurant_nps': round(random.uniform(35,42),1),
            'cac': rnd(2620,6), 'ltv_cac': round(random.uniform(2.1,2.6),1),
            'take_rate': round(random.uniform(11.8,13.1),1),
        },
        'platform': {'total_mau': rnd(305200,3)},
    }

def _kv(key):
    import requests as _rq
    try:
        r = _rq.post('http://3.211.238.155:9100/api/kv/get',
            json={'key': key},
            headers={'X-Auth-Token': KV_TOKEN},
            timeout=8)
        return r.json().get('value', '') if r.status_code == 200 else ''
    except:
        return ''

FALLBACK_INSIGHTS = [
    {'id':'freq','type':'alert','sev':'high','icon':'REDSQ','confidence':0.92,
     'product':'Chocofood','title':'Order freq 1.97x vs 3.8x Uber Eats',
     'body':'Gap 1.83x. CLV/CAC falls from 21x to 5x without frequency fix.',
     'action':'Launch Choco+ subscription: unlimited delivery for 2990 тг/month'},
    {'id':'kaspi','type':'alert','sev':'critical','icon':'REDSQ','confidence':0.94,
     'product':'Chocofood','title':'Kaspi 8.2M MAU enters restaurants',
     'body':'Kaspi launched restaurant cashback. 45x our MAU. Loyalty threat.',
     'action':'Pivot SR pitch: operational value > loyalty'},
    {'id':'cm','type':'insight','sev':'medium','icon':'BULB','confidence':0.87,
     'product':'Chocofood','title':'CM -9.2% — three levers to zero',
     'body':'Subsidy 14.9% GMV vs benchmark 10%. Courier util 62% vs target 75%.',
     'action':'Cut subsidies from 14.9% to 11% via smart targeting'},
    {'id':'ads','type':'opportunity','sev':'high','icon':'BULB','confidence':0.89,
     'product':'Chocofood','title':'Ads Revenue 5.8% vs 28.4% DoorDash',
     'body':'Massive upside in promoted listings monetization.',
     'action':'Launch Ads Dashboard for restaurants Q1 2026'},
    {'id':'astana','type':'opportunity','sev':'medium','icon':'GRNSQ','confidence':0.76,
     'product':'Smart Restaurant','title':'Astana: new users +18% WoW',
     'body':'Premium segment uncovered by competitors.',
     'action':'Pilot 5 anchor restaurants in Astana Q2 2026'},
    {'id':'funnel','type':'watch','sev':'medium','icon':'YLWSQ','confidence':0.83,
     'product':'Ecosystem','title':'New visitors -5.3% WoW — leading indicator',
     'body':'Historical lag to buyer drop: ~8 weeks.',
     'action':'Trigger: ratio < 0.25 => emergency UA campaign'},
]

INSIGHT_CACHE = list(FALLBACK_INSIGHTS)
INSIGHT_META  = {'last_generated': None, 'source': 'fallback', 'model': None,
                  'generation_ms': 0, 'error': None}

_LENSES = [
    ('freq',       'Order Frequency Gap',       'order_freq={freq}x/mo vs Uber Eats 3.8x. CAC {cac} tenge. Why twice/month not 4x? DashPass subscription mechanics, habit formation window, Choco Plus path.'),
    ('cm',         'Contribution Margin Path',  'CM is {cm}%. Three levers: subsidy cut, courier util 62pct to 75pct, take rate 12.4pct to 15pct. What to move first? What breaks at which speed?'),
    ('kaspi',      'Kaspi Threat Assessment',   'Kaspi 8.2M MAU vs {mau} users — 45x gap. Restaurant cashback live, QR in 1200 restaurants. Existential or manageable in 18-month scenario?'),
    ('cohort',     'Cohort Retention Analysis', 'M1 53pct, M6 25pct, M12 19pct. First 30 days determine Power User vs churner. Day-3, day-7, day-14 windows. What bends the retention curve?'),
    ('pricing',    'Pricing and Take Rate',     'Take rate 12.4pct vs Uber Eats 17.2pct. Restaurant NPS only 38. Tiered commission model? Dynamic delivery fees? Elasticity before partner revolt?'),
    ('ops',        'Courier Operations',        'Utilization 62pct, target 75pct. 8.1 orders per courier vs DoorDash 14.2. On-time 83.8pct. Lunch peak 94pct. Root cause: dispatch, restaurants, or zone density?'),
    ('growth',     'City Expansion Strategy',   'Almaty 65pct GMV. Aktobe +82pct YoY, Atyrau +95pct YoY. Tier-2 unit economics better than Almaty. Playbook for 3 more cities in 12 months?'),
    ('risk',       'Downside Risk Scenarios',   'Kaspi subsidizes 18 months; Glovo drops fee to 490 tenge; top-20 restaurants demand 12pct or leave. Kill scenario vs manageable? Response playbook?'),
    ('ltv',        'LTV Maximization',          'LTV/CAC {ltv}x, target 4x+. Frequency is the lever. Subscription vs loyalty vs gamification — which moves LTV without raising CAC {cac} tenge?'),
    ('aov',        'Average Order Value',       'AOV {aov} tenge. Group orders, premium restaurants, late-night premium, upsells. Which AOV drivers are real vs noise? Realistic ceiling?'),
    ('cac',        'CAC and Payback Period',    'CAC {cac} tenge, long payback period. Which channels deliver sub-2000 tenge CAC? Organic vs paid vs referral. How to get payback under 6 months?'),
    ('peak',       'Peak Time and Load',        'Lunch peak 94pct utilization — system breaks when revenue is highest. Sunday vs weekday shape. Late-night orders: share, AOV, profitability?'),
    ('almaty',     'Almaty Unit Economics',     'Almaty 65pct GMV but worst CM — subsidy war ground zero. Which zones are CM-positive? Where to defend vs cede to Glovo and Yandex?'),
    ('dark',       'Dark Kitchen Opportunity',  'Dark kitchens cut delivery time 35pct, improve restaurant CM 8-12pct. Owned vs partner model. Almaty pilot: 15M tenge capex, 18-month payback math?'),
    ('restaurant', 'Restaurant Partner Health', 'Restaurant NPS 38 — dangerously low. Top complaints? GMV concentration risk in top-50. Commission 18pct vs Glovo 20pct — why still unhappy?'),
    ('b2b',        'Corporate B2B Channel',     'Almaty 50K+ office workers. Corporate AOV 2.3x consumer. Bulk orders, invoice billing, account management. B2B product worth building?'),
    ('saturday',   'Weekend Pattern Analysis',  'Weekends reveal the real Chocofood customer. Saturday lunch vs Friday dinner profiles. Different restaurant mix, different retention impact on LTV?'),
    ('promo',      'Promotion ROI Analysis',    'Promos eating CM. First-order discount vs free delivery vs restaurant-funded. Which promos improve LTV vs buy cheap churners? Cohort-level ROI?'),
    ('yandex',     'Yandex Food Response',      'Yandex Food: strong CIS brand, 18-22pct take rate. Actively subsidizing Kazakhstan? Which markets contested? Where winning on restaurant breadth?'),
    ('glovo',      'Glovo Competitive Gap',     'Glovo 690 tenge delivery vs our 432, yet 38pct market share. Why pay more? Restaurant selection, UX, brand perception. Where are we genuinely better?'),
    ('new_city',   'New City Launch Playbook',  'Aktobe +82pct, Atyrau +95pct YoY. What made these succeed? Can we systematize minimum viable restaurant density and courier seeding for 5 more cities?'),
    ('courier',    'Courier Supply Quality',    'Util 62pct — overcapacity off-peak, crunch at lunch. Daily earnings vs competitors? Retention rate? What drives churn and how to stop it?'),
    ('product',    'Product Feature Priority',  'What features move freq from {freq}x to 3x? Scheduled orders, group orders, subscription, loyalty. DoorDash and Grab feature sets vs ours?'),
    ('brand',      'Brand and Market Position', 'In a market with Kaspi 8.2M MAU, Glovo, Yandex — what does Chocofood stand for? Local brand vs global players: underleveraged asset or irrelevant?'),
]

_LENS_DECK: list = []

_lens_i = 0
_FALLBACK_T = [
    "The frequency gap keeps nagging at me. 1.97 times per month — our average user orders food delivery less than twice a month. Uber Eats sits at 3.8x. Almost double. And this is not just a vanity metric, it is the entire LTV story. Every incremental order from an existing user costs us near-zero in additional CAC. Moving from 1.97x to 3x without acquiring one new user would lift LTV by roughly 50 percent. The question is why people stop at twice a month. I suspect it is habit formation, or rather its total absence. DoorDash cracked this with DashPass. Once you pay a monthly fee, the psychological cost of each marginal order drops to zero. You order more because the incremental cost feels free. A Choco Plus subscription at 2990 tenge per month could completely rewire user behavior. The key is getting the first 10000 subscribers to validate the model before scaling acquisition.",
    "The unit economics are where this business lives or dies. We are running at negative contribution margin. Every order costs us more to fulfill than we earn from it. The path to zero, let alone positive, requires moving three levers simultaneously. First, delivery subsidy reduction from 575 tenge to 380. That is the bluntest tool but the fastest win on the income statement. Second, courier utilization from 62 percent to 75 percent — same courier fleet, meaningfully more orders per shift. Third, take rate from 12.4 to 15 percent, which requires better restaurant negotiations. The problem is sequencing. If we cut subsidy too fast, order volume drops and utilization gets worse. If we raise take rate first, restaurants react and their NPS — already at 38 — collapses further. These are not three separate levers. They are one interconnected machine that must be tuned carefully and in the right sequence.",
    "45 times our audience. That is Kaspi. 8.2 million monthly active users versus our 182 thousand. And they just activated restaurant cashback across the entire platform. The optimistic read is that cashback alone does not win food delivery. You need couriers, restaurant density, sub-30-minute delivery times, and operational muscle built over years. We have all of those things. The pessimistic read is that Kaspi can subsidize losses for 24 months while we cannot match their balance sheet. The real question is intent. Is this a casual category expansion or a strategic priority? The QR payment integration in 1200 Almaty restaurants suggests it is strategic. They are building infrastructure, not just running a promotional campaign. Our response cannot be a price war. Our response must be operational excellence in dimensions where Kaspi cannot easily follow — reliability, restaurant relationships, delivery speed.",
    "M1 retention at 53 percent looks reasonable until you see M12 at 19 percent. That means 4 in 5 users who were active in month one have stopped ordering entirely by month 12. The first 30 days determine everything. I keep thinking about what separates users who become high-frequency from users who order once and disappear. It probably comes down to one specific experience — the order that arrived in 18 minutes, the restaurant they had never tried before, the night the service felt almost magical. Our job is to manufacture that magic more reliably. Day 3 onboarding push. Day 7 coupon. Day 14 — the habit formation window that behavioral research consistently points to. Each of these touchpoints is cheap. The alternative, re-acquiring churned users, costs 2620 tenge per user. Bending the M3 retention curve by even 5 percentage points compounds dramatically over 12 months across the full cohort.",
    "Take rate at 12.4 percent when Uber Eats runs 17.2 percent means we are leaving significant revenue on the table from every single order. But it is not that simple. Restaurant NPS is already only 38 — dangerously low. If we raise commission from 18 percent, we risk losing our best restaurant partners to Glovo or Yandex who are actively recruiting them. The smarter move is a tiered commission structure — 15 percent for standard partners, 12 percent for top-tier exclusive partners who get premium placement and co-marketing support in return. This increases blended take rate while giving restaurants a clear path to better terms. DoorDash ran this exact playbook with great success. Dynamic delivery fees are the second lever — charge more during peak hours when demand exceeds supply, less during slow periods to stimulate volume. Surge pricing is psychologically difficult to introduce but financially powerful once normalized.",
    "Eight point one orders per courier per day. DoorDash delivers 14.2. That gap is not just an efficiency number — it is the structural reason our contribution margin is negative. Every courier we are paying who is not actively delivering an order is pure operating cost. Utilization at 62 percent means our couriers are idle 38 percent of working time. But the distribution is everything. During the lunch rush we hit 94 percent utilization — the system is visibly breaking under load. At 2pm, couriers are waiting by their phones. The fundamental problem is zone density. We do not have enough orders per square kilometer outside of peak hours to keep couriers continuously moving. Dark kitchens reduce average delivery distance. Dynamic zone management helps route couriers more efficiently. But the real fix is volume — more orders in the same geography makes everything better simultaneously and is the only sustainable path forward.",
    "Almaty has become our defensive position rather than our growth engine. 65 percent of GMV but also the market where we spend the most subsidizing orders to compete with Glovo and Yandex. The cities that are growing fastest — Aktobe at 82 percent year over year, Atyrau at 95 percent — are telling us something important. In markets where competitors are less aggressively present, our unit economics are dramatically better. Less subsidy pressure, better courier utilization, higher restaurant NPS from partners who have fewer alternatives. The tier-2 city playbook is an underexplored strategic asset. We need minimum viable restaurant density — probably 80 quality restaurants — plus courier seeding of 50 to 60 people, plus focused demand generation in the first 90 days. Three new tier-2 cities with positive contribution margin by month 6 would fundamentally change our portfolio narrative.",
    "Let me think through the three worst scenarios seriously. First: Kaspi goes all-in and subsidizes food delivery at a loss for 18 months, deploying their 8.2 million user base aggressively. Our response here must lean into operational advantages rather than matching their price — speed, reliability, restaurant relationships in dimensions Kaspi cannot quickly replicate. Second: Glovo drops delivery fee to 490 tenge, below our 432. This is a temporary subsidy war from a company for whom Kazakhstan is not a primary market. We survive this by improving our own efficiency simultaneously. Third, and honestly most dangerous: our top 20 restaurant partners collectively demand 12 percent commission or threaten to leave. These restaurants represent perhaps 40 percent of total GMV. Losing even half of them would crater both take rate and order volume at the same time. This requires proactive relationship investment today, not during the crisis.",
    "LTV over CAC is the fundamental measure of whether our business model works at scale. At 2.4x we are dangerously close to the threshold where aggressive user acquisition destroys value rather than creates it. We need 4x minimum to justify the pace of marketing spend that growth requires. The math is straightforward: at 1.97 orders per month with current average order value and contribution margin, a user takes about 14 months to pay back their acquisition cost. That is too long for a growth-stage company. Two paths forward. First and most impactful: increase frequency, which is the highest-leverage LTV lever available. Second: push contribution margin positive so each order contributes meaningfully. At 3x frequency and zero percent CM, payback drops to 8 months. At 3x frequency and 3 percent CM, it drops to 5 months. Suddenly the acquisition machine makes clear financial sense.",
    "Average order value at 3850 tenge is the quiet metric that gets overlooked in favor of the louder ones like GMV and user growth. It is not in crisis, but it has real upside we are systematically failing to capture. Group orders represent the largest unlocked opportunity — when 3 people in an office order together, the basket size is typically 2.8x a solo order but delivery cost is exactly the same. Premium restaurant curation adds meaningfully to AOV — a user who discovers an upscale Almaty restaurant might place a 6000 tenge order versus the platform average. Late-night orders, placed after 9pm, carry an implicit premium because users are ordering when alternatives are genuinely limited. Even a 10 percent sustainable increase in AOV at constant order volume flows directly through to take rate revenue with zero additional cost. The product team should be running experiments on group order UI and premium restaurant curation.",
    "Customer acquisition cost at 2620 tenge with a payback period well over 12 months — this is the number that makes growth economics difficult to defend. The important question is not what the blended CAC is but what the channel breakdown looks like underneath it. Paid social and performance marketing typically have the highest CAC in food delivery markets. Referral programs typically run 40 to 60 percent below blended CAC because the referred user arrives pre-validated by a trusted friend who had a positive experience. If referral accounts for only 15 percent of our acquisition today, growing that channel to 35 percent could reduce blended CAC by 15 to 20 percent without spending any additional marketing dollars. App store optimization is similarly underinvested — organic high-intent downloads in a category like food delivery are significant at scale and cost near-zero per install compared to any paid channel.",
    "94 percent courier utilization at the lunch peak is not a success metric — it is a warning signal that the system is operating dangerously close to failure. When utilization exceeds 90 percent, delivery times degrade, order cancellations spike, and NPS scores drop in real time precisely when the most users are watching. The system is designed to break at exactly the moment it most needs to perform. Saturday midday patterns likely reveal something similar for weekend demand spikes. Late-night orders after 9pm represent the opposite problem — low volume means couriers are idle, but the users who order late at night are frequently high-value, high-frequency customers testing whether the platform is reliable for their most urgent moments. Getting those orders right matters disproportionately for long-term LTV. The solution to peak overload is not simply adding more couriers — it is zone-based demand smoothing and honest delivery time transparency before the order is placed.",
    "Almaty is 65 percent of GMV but probably 90 percent of our total subsidy spend. The competitive pressure from Glovo and Yandex is most intense here, restaurant partner expectations are highest, and courier costs are highest. And yet we cannot tactically abandon Almaty — it is the reference market, the media market, the talent attraction market. The strategic question is which Almaty zones are genuinely worth defending and which are not. I suspect central Almaty and the premium residential districts are CM-positive at reasonable subsidy levels. Far suburban zones with low restaurant density and long delivery distances might be structurally unprofitable regardless of how aggressively we optimize operations. A zone-level contribution margin analysis would almost certainly reveal that 30 percent of Almaty delivery areas consume 70 percent of the subsidy budget. Selectively defunding those zones could meaningfully improve CM without significantly reducing overall platform revenue.",
    "Dark kitchens solve a specific operational problem elegantly. When a popular restaurant is located far from where most of its orders originate geographically, delivery times suffer and restaurant contribution margin suffers with them. A dark kitchen positioned in the right part of the city — no front-of-house, no dine-in space, purely optimized for delivery production — can cut average delivery time by 35 percent and improve the partner restaurant effective margin by 8 to 12 percentage points. The question for Chocofood is whether to own dark kitchen assets or facilitate them as a marketplace layer. Owning requires capital commitment of approximately 15 million tenge per kitchen but also provides much higher margin on those orders and complete quality control. Facilitating maintains asset-light marketplace economics but sacrifices control over the customer experience. The pilot that makes strategic sense: identify the 3 highest-demand restaurant categories in Almaty with the worst delivery times.",
    "Restaurant NPS at 38 means nearly half of our restaurant partners would not actively recommend working with the Chocofood platform. This is a slow-burning strategic risk. Our top 20 restaurants by GMV likely represent 40 percent or more of total platform revenue. If those restaurants collectively decided to test listing exclusively on Glovo for 60 days as a negotiating tactic, we would immediately discover exactly how dependent we are on their participation. The NPS number almost certainly reflects three distinct pain points: commission rates that feel high relative to the incremental value our platform provides, operational friction in the restaurant-facing dashboard and order management tools, and inconsistent courier behavior at the restaurant pickup moment that reflects poorly on the restaurant in the eyes of customers. Commission is difficult to reduce given our current contribution margin situation. The other two are engineering and training problems with clear solutions available.",
    "Every corporate office district in Almaty represents an untapped addressable market with structurally better unit economics than consumer delivery. Office workers ordering lunch together behave differently from individual consumers — higher order value because groups naturally coordinate, more predictable demand patterns because lunch happens daily at consistent times, lower effective CAC because word spreads rapidly through office social networks. The B2B product we should be building is not technically complicated: group ordering with integrated split payment, monthly invoice billing for corporate finance departments, a dedicated account manager relationship for organizations above 50 employees. DoorDash for Work generates roughly 12 percent of total US revenue from this single product line. The Almaty corporate addressable market is probably 10 to 15 thousand office workers within practical delivery range of quality restaurants — a meaningful segment with better unit economics than consumer delivery.",
    "Weekend order patterns reveal something important about the actual Chocofood customer that weekday data obscures. Weekday orders are predominantly driven by time pressure — people too busy to cook, ordering lunch at their desks or a quick dinner before a late night at work. Weekend orders are fundamentally different in motivation. Saturday lunch might be a family deciding collaboratively what to eat together, producing a meaningfully higher basket size. Sunday evening might be young urban adults who want comfort food delivered after a day out. The restaurant category mix shifts significantly — weekend orders probably skew toward brunch spots, comfort food, and premium delivery experiences over the quick-service weekday categories. Whether weekend users are higher or lower frequency overall is a critical segmentation question that should drive very different retention interventions for each customer group.",
    "Promotions are the most expensive form of strategic optimism in food delivery. Every discount is a bet that the user we subsidize today will become profitable at some point in the future. The ROI varies enormously by promotion type. First-order discounts disproportionately attract bargain-seeking users who will wait for the next promotional offer before ordering again — effectively negative lifetime value customers we keep reacquiring at cost. Referral bonuses attract users who arrive with social proof and demonstrated platform commitment from a peer who had a positive experience — dramatically better LTV profile on average. Restaurant-funded promotional offers shift the cost to the partner while increasing order volume, making them the most efficient promotional structure in theory. The measurement framework we actually need is cohort-level promotional ROI: for every 1000 tenge spent by promo type, what is the 12-month LTV of the resulting user cohort? That data would let us eliminate unprofitable promo types completely.",
    "Yandex Food carries the CIS brand playbook and cultural knowledge that Glovo simply does not have. They understand the local market linguistically and culturally, and they have been operating food delivery in Russia and adjacent markets long enough to have real operational knowledge of what works in this consumer context. Their reported take rate of 18 to 22 percent suggests they have developed meaningful pricing power with restaurant partners — likely because their brand recognition drives measurable incremental traffic that justifies the higher commission. The strategic question for us is investment intensity. Is Kazakhstan a genuine priority market for Yandex Food or a secondary territory they maintain out of operational momentum? If secondary, they will not sustain aggressive subsidy campaigns for an extended period. If Kazakhstan is becoming a strategic priority, their balance sheet resources dwarf what we can deploy in response, and we need to find asymmetric competitive positions quickly.",
    "Glovo charges 690 tenge delivery fee versus our 432 and still commands 38 percent market share. That pricing gap should not persist in a rational consumer market unless Glovo is delivering meaningfully more value. The most likely explanations in rank order of probability: restaurant selection is substantially broader, particularly the premium and international restaurant brands that aspirational users specifically want to order from; the app experience has a higher perceived quality in reliability and UX; brand association with being a global premium platform matters to a specific valuable user segment. The implications are significant and different for each explanation. If restaurant breadth is the primary gap, we need a targeted acquisition campaign for the top 50 Glovo-exclusive restaurants in Almaty. If it is brand perception, that requires a longer program to shift. If it is app quality, it is an engineering investment problem with a solvable answer. We need to know the actual rank ordering through proper user research.",
    "Aktobe grew 82 percent year over year. Atyrau grew 95 percent. These numbers should be generating much more internal strategic attention than they currently appear to receive. Both cities are growing at nearly double the platform average with apparently better unit economics than Almaty. The tier-2 city hypothesis is becoming validated data rather than a speculative thesis. The critical question is what specifically made these launches successful. My best hypothesis: minimum viable restaurant density was achieved — probably around 80 quality restaurants — couriers were properly seeded in the first 90 days to ensure acceptable delivery times, and there was no established competitor willing to spend aggressively to defend the market position. The second question is what the next 5 cities look like. Shymkent is already at 7 percent of GMV and growing. Karaganda, Pavlodar, and Ust-Kamenogorsk are all industrial cities with expanding middle-class populations and no dominant food delivery incumbent currently in place.",
    "Courier utilization at 62 percent means we are effectively paying for 38 percent idle time across our courier fleet. Outside of the lunch rush, couriers are waiting with nothing to deliver. The obvious operational fix — reduce courier supply — immediately creates a new problem: when the next order arrives, nobody is in position and delivery times spike, damaging both NPS and order completion rates simultaneously. This is the fundamental supply-demand matching tension in any delivery marketplace. DoorDash addressed this with incentive structures that encouraged couriers to work peak demand hours and effectively disincentivized working during slow periods when utilization would be low. Courier earnings transparency matters enormously for fleet quality and retention. If our couriers earn measurably less than Glovo couriers for identical hours of work, we end up with adverse selection — better-performing couriers migrate to better-paying competitors and we retain only those who cannot find alternatives.",
    "The product feature backlog is where strategic choices get made implicitly through prioritization decisions, often without explicit acknowledgment of the downstream consequences. Every feature we build that touches order frequency has compounding effects — it affects every subsequent order from every user who experiences it. Scheduled orders solve a specific and recurring user pain: the family planning Sunday dinner or the office planning group lunch for the week. Group orders solve the social coordination problem that currently causes colleagues to abandon food delivery entirely and just pick a single restaurant by messaging app. Both features are technically achievable but require real UX investment to do well. The highest ROI product investment is almost certainly the subscription tier, not because subscription models are inherently magical, but because they force an explicit frequency commitment that structurally changes the user relationship with the platform from purely transactional to genuinely habitual.",
    "What does Chocofood actually mean to a user in Almaty? I am genuinely not sure we have a clear answer to this question, and I suspect that ambiguity is costing us in ways that are difficult to measure directly. In a competitive landscape where Kaspi has 8.2 million users who already trust the brand across payments and loans, where Glovo carries a premium international brand identity, and where Yandex has substantial CIS cultural credibility — what is our specific positioning? The local Kazakhstani company delivering food in Kazakhstan is potentially a genuinely powerful brand asset in a market where consumers are showing meaningful preference for domestic alternatives. But we have probably never clearly articulated this positioning or tested rigorously whether it moves consumer behavior in our favor. Brand clarity does not require advertising spend. It requires one sentence that every team member knows that explains precisely what Chocofood stands for and why a user should choose us.",
]

_fallback_ti = 0

def _refresh_loop():
    global INSIGHT_CACHE, INSIGHT_META, OPENAI_KEY
    OPENAI_KEY = _kv('openai_api_key')
    while True:
        m = gen_metrics()
        if OPENAI_KEY and _has_openai:
            cf = m.get('chocofood', {})
            prompt = ('Chocofood metrics: freq=' + str(cf.get('order_freq',1.97)) +
                     'x cm=' + str(cf.get('cm_pct',-9.2)) +
                     '% mau=' + str(cf.get('mau',182000)) +
                     ' cac=' + str(cf.get('cac',2620)) +
                     ' ltv_cac=' + str(cf.get('ltv_cac',2.4)) + 'x')
            t0 = time.time()
            try:
                client = _oai.OpenAI(api_key=OPENAI_KEY)
                r = client.chat.completions.create(
                    model='gpt-4o-mini',
                    messages=[{'role':'system','content':'Senior BI analyst for Chocofood Kazakhstan. Return exactly 6 insights as JSON array. Each: {id,type(alert|insight|opportunity|watch),sev(critical|high|medium|low),icon(REDSQ|BULB|GRNSQ|YLWSQ),confidence,product,title,body,action}. Return ONLY valid JSON array.'},
                              {'role':'user','content':prompt}],
                    response_format={'type':'json_object'}, temperature=0.7, max_tokens=1500,
                )
                raw = json.loads(r.choices[0].message.content or '{}')
                items = raw if isinstance(raw, list) else list(raw.values())[0]
                if items and isinstance(items, list):
                    for it in items:
                        it['is_new'] = True
                        it['llm'] = True
                    INSIGHT_CACHE = items[:6]
                    INSIGHT_META = {'last_generated': datetime.datetime.now().isoformat(),
                                    'source': 'llm', 'model': 'gpt-4o-mini',
                                    'generation_ms': round((time.time()-t0)*1000), 'error': None}
            except Exception as e:
                INSIGHT_META['error'] = str(e)[:100]
        time.sleep(REFRESH_SEC)

@app.on_event('startup')
async def startup():
    threading.Thread(target=_refresh_loop, daemon=True).start()

# ============================================================
# API ROUTES — must be defined BEFORE the SPA catchall
# ============================================================

@app.get('/api/platform')
async def platform(): return gen_metrics()

@app.get('/api/metrics')
async def metrics(): return gen_metrics()

@app.get('/api/insights')
async def insights(limit: int = 6):
    out = list(INSIGHT_CACHE[:limit])
    for it in out: it['is_new'] = random.random() > 0.5
    return out

@app.get('/api/insights/status')
async def insights_status(): return INSIGHT_META

@app.get('/api/competitors')
async def competitors():
    return [
        {'name':'Kaspi.kz','value':str(round(random.uniform(8.1,8.3),1))+'M','threat':9,'col':'#c0392b','move':'Рестораны: cashback запущен'},
        {'name':'Glovo KZ','value':str(rnd(12000,8)),'threat':7,'col':'#e67e22','move':'Delivery fee -200 тг'},
        {'name':'Yandex KZ','value':str(rnd(8000,10)),'threat':5,'col':'#f39c12','move':'Замедление -3.2% YoY'},
        {'name':'2GIS','value':'2.1M','threat':3,'col':'#27ae60','move':'Отзывы расширяются'},
    ]

@app.get('/api/history')
async def history():
    return [{'label':'W'+str(i+1),'mau':int(80000+i*3000+random.randint(-2000,2000)),
             'buyers':int(26000+i*700+random.randint(-500,500)),
             'cac':int(2200+i*60+random.randint(-100,100))} for i in range(12)]

@app.get('/api/actions')
async def get_actions():
    m  = gen_metrics()
    cf = m.get('chocofood', {})
    sr = m.get('sr', {})
    ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    freq = cf.get('order_freq', 1.97)
    cac  = cf.get('cac', 2620)
    gmv  = cf.get('gmv_month', 700000000)
    cm   = cf.get('cm_pct', -9.2)
    locs = sr.get('locations', 89)
    mau  = cf.get('mau', 182000)
    return [
        {'id':'tg_freq','type':'telegram','icon':'📱','status':'pending','priority':'high',
         'title':'Alert: Order Frequency ' + str(freq) + 'x/мес',
         'description':'Frequency ' + str(freq) + 'x — critical gap vs Uber Eats 3.8x.',
         'preview':'🚨 Chocofood Intelligence Alert\n' + ts + '\n\nOrder Frequency: ' + str(freq) + 'x/month\nBenchmark (Uber Eats): 3.8x\nGap: ' + str(round(3.8-freq,2)) + 'x\n\nMAU: ' + str(mau) + ' | GMV: ' + str(round(gmv/1e6)) + 'M тг\n\n→ Action: Launch Choco+ subscription pilot.'},
        {'id':'cu_cac','type':'clickup','icon':'✅','status':'pending','priority':'high',
         'title':'Task: Audit CAC channels — ' + str(cac) + ' тг',
         'description':'Blended CAC ' + str(cac) + ' тг. Identify and cut underperforming channels.',
         'preview':'CAC Channel Audit\n\nCurrent CAC: ' + str(cac) + ' тг\nTarget: < 2,000 тг\n\n1. Pull CAC by channel\n2. Identify bottom 2 by LTV/CAC\n3. Reallocate budget\n\nDue: +7 days'},
        {'id':'gmail_digest','type':'email','icon':'📧','status':'pending','priority':'medium',
         'title':'Email: Weekly Chocofood Digest',
         'description':'AI-generated weekly summary → anvar.b@chocolife.kz',
         'preview':'Subject: Chocofood Weekly Intelligence — ' + datetime.datetime.now().strftime('%d %b %Y') + '\n\nGMV: ' + str(round(gmv/1e6)) + 'M тг/month\nOrder freq: ' + str(freq) + 'x (target: 3.5x)\nCM%: ' + str(cm) + '%\nMAU: ' + str(mau) + '\n\nTop Alert: Kaspi launched restaurant cashback.\n\nRecommended: Launch Choco+ this quarter.'},
        {'id':'cu_sr','type':'clickup','icon':'✅','status':'pending','priority':'high',
         'title':'Task: SR Activation — ' + str(locs) + '/150 locations',
         'description':str(locs) + ' of 150 target locations. Accelerate onboarding pipeline.',
         'preview':'SR Activation Sprint\n\nCurrent: ' + str(locs) + '/150 locations\nGap: ' + str(150-locs) + ' needed\n\n1. 30 warm leads from pipeline\n2. Reduce activation: 24d → 14d\n3. Dedicated CSM per new signup'},
        {'id':'report','type':'report','icon':'📋','status':'pending','priority':'low',
         'title':'View Executive Report',
         'description':'Clean executive view with live KPIs, AI narrative, top insights.',
         'preview':'Opens the Report page with live data and AI executive summary.'},
    ]

@app.post('/api/action/execute')
async def execute_action(body: dict):
    action_type = body.get('type', '')
    preview     = body.get('preview', '')
    title       = body.get('title', '')
    import requests as _rq
    if action_type == 'telegram':
        bt = _kv('choco_telegram_bot_token')
        ci = _kv('choco_telegram_chat_id')
        if not bt or not ci:
            return {'status':'error','message':'Telegram credentials not found'}
        r = _rq.post('https://api.telegram.org/bot' + bt + '/sendMessage',
            json={'chat_id': ci, 'text': preview}, timeout=10)
        return {'status':'success' if r.status_code==200 else 'error',
                'message':'Sent to Telegram ✓' if r.status_code==200 else r.text[:100]}
    elif action_type == 'clickup':
        token = _kv('choco_clickup_token')
        lid   = _kv('choco_clickup_list_id')
        if not token or not lid:
            return {'status':'error','message':'ClickUp credentials not found'}
        r = _rq.post('https://api.clickup.com/api/v2/list/' + lid + '/task',
            headers={'Authorization': token,'Content-Type':'application/json'},
            json={'name':title,'description':preview,'priority':2,'tags':['chocofood','ai']},
            timeout=10)
        d = r.json()
        if r.status_code in [200,201]:
            return {'status':'success','message':'Task created in ClickUp ✓ (id: ' + str(d.get('id','')) + ')'}
        return {'status':'error','message':str(d)[:200]}
    elif action_type == 'email':
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
            token_raw = _kv('google_oauth_token_sheets')
            if not token_raw:
                return {'status':'error','message':'Gmail token not found'}
            td = json.loads(token_raw)
            creds = Credentials(token=td.get('token'),refresh_token=td.get('refresh_token'),
                token_uri=td.get('token_uri','https://oauth2.googleapis.com/token'),
                client_id=td.get('client_id'),client_secret=td.get('client_secret'),scopes=td.get('scopes'))
            if creds.expired and creds.refresh_token: creds.refresh(Request())
            ln = preview.split('\n')
            subj = ln[0].replace('Subject: ','') if ln else title
            msg = MIMEText('\n'.join(ln[1:]).strip(), 'plain', 'utf-8')
            msg['to']      = 'anvar.b@chocolife.kz'
            msg['from']    = 'anvarbakiyev@gmail.com'
            msg['subject'] = subj
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            svc = build('gmail','v1',credentials=creds)
            res = svc.users().messages().send(userId='me',body={'raw':raw}).execute()
            return {'status':'success','message':'Email sent to anvar.b@chocolife.kz ✓'}
        except Exception as e:
            return {'status':'error','message':str(e)[:300]}
    return {'status':'error','message':'Unknown action type: ' + action_type}

@app.get('/api/report')
async def get_report():
    m = gen_metrics()
    cf = m.get('chocofood',{})
    return {
        'generated_at': datetime.datetime.now().isoformat(),
        'period': datetime.datetime.now().strftime('%B %Y'),
        'metrics': {'gmv':cf.get('gmv_month',700000000),'mau':cf.get('mau',182000),
                    'orders':cf.get('orders_month',178000),'aov':cf.get('aov',3850),
                    'freq':cf.get('order_freq',1.97),'cm_pct':cf.get('cm_pct',-9.2),
                    'on_time':cf.get('on_time_pct',83.8),'ltv_cac':cf.get('ltv_cac',2.4),
                    'take_rate':cf.get('take_rate',12.4),'cac':cf.get('cac',2620)},
        'top_insights': list(INSIGHT_CACHE[:3]),
        'benchmarks': {'freq_benchmark':3.8,'cm_benchmark':4.8,'ltv_cac_benchmark':6.8},
    }

@app.get('/api/think')
async def think_stream():
    async def gen():
        global _lens_i, _fallback_ti, _LENS_DECK
        while True:
            m  = gen_metrics()
            cf = m.get('chocofood', {})
            if not _LENS_DECK:
                import random as _rng
                _LENS_DECK[:] = list(range(len(_LENSES)))
                _rng.shuffle(_LENS_DECK)
            li = _LENS_DECK.pop(0)
            lid, ltitle, lprompt = _LENSES[li]
            filled = lprompt.format(
                freq=cf.get('order_freq',1.97), cm=cf.get('cm_pct',-9.2),
                mau=int(cf.get('mau',182000)), cac=int(cf.get('cac',2620)),
                ltv=cf.get('ltv_cac',2.4), aov=int(cf.get('aov',3850)))
            meta = json.dumps({'lid': lid, 'title': ltitle})
            yield 'data: META:' + meta + '\n\n'
            await asyncio.sleep(0.01)
            if OPENAI_KEY and _has_openai:
                try:
                    client = _oai.OpenAI(api_key=OPENAI_KEY)
                    stream = client.chat.completions.create(
                        model='gpt-4o-mini',
                        messages=[{'role':'system','content':'Senior analyst thinking out loud about Chocofood Kazakhstan. 200-280 words, flowing paragraphs, specific numbers. No bullets, no headers.'},
                                  {'role':'user','content': filled}],
                        stream=True, max_tokens=400, temperature=0.85)
                    for chunk in stream:
                        tok = chunk.choices[0].delta.content if chunk.choices else None
                        if tok:
                            yield 'data: ' + tok.replace('\n',' ') + '\n\n'
                except Exception as e:
                    yield 'data: [error: ' + str(e)[:60] + '] \n\n'
            else:
                fi = li % len(_FALLBACK_T)
                for w in _FALLBACK_T[fi].split(' '):
                    yield 'data: ' + w + ' \n\n'
                    await asyncio.sleep(0.143)
            # ── generate 1-sentence actionable conclusion ──
            _conclude_map = {
                'freq':    'Launch Choco+ subscription at \u20b82,990/mo to push order frequency from 1.97x to 3.8x.',
                'cm':      'Cut delivery subsidy from \u20b8575 to \u20b8380 and raise take rate to 14% to reach CM breakeven by Q4.',
                'kaspi':   'Compete on speed and merchant depth where Kaspi cannot replicate — not on price.',
                'cohort':  'Trigger day-3 onboarding push + day-7 coupon to retain 15% more M1 users.',
                'pricing': 'Pilot tiered commission 15%/12% with top 50 restaurants to close take rate gap.',
                'ops':     'Add 200 Almaty lunch-zone couriers to raise utilization from 62% to 75%.',
                'growth':  'Double down on Aktobe (+82% YoY) and Atyrau (+95% YoY) — best unit economics.',
                'risk':    'Build 6-month war chest matching Kaspi subsidy scenario before raising prices.',
            }
            _conc = _conclude_map.get(lid, 'Focus resources on the highest-impact metric identified.')
            if OPENAI_KEY and _has_openai:
                try:
                    _cc = _oai.OpenAI(api_key=OPENAI_KEY)
                    _cr = _cc.chat.completions.create(
                        model='gpt-4o-mini',
                        messages=[
                            {'role':'system','content':'Give ONE actionable sentence, 15-20 words. Start with a verb. Be specific with numbers from the context.'},
                            {'role':'user','content':f'Key insight for {ltitle} in Chocofood Kazakhstan: {filled[:400]}'}
                        ],
                        max_tokens=55, temperature=0.6, stream=False)
                    _conc = _cr.choices[0].message.content.strip().replace('\n',' ')
                except Exception:
                    pass
            yield 'data: CONCLUDE:' + _conc + '\n\n'
            await asyncio.sleep(0.05)
            yield 'data: PAUSE:\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(gen(), media_type='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no','Access-Control-Allow-Origin':'*'})

# ============================================================
# STATIC ROUTES — after all API routes
# ============================================================

if STATIC.exists():
    @app.get('/brain')
    async def brain(): return FileResponse(STATIC/'brain.html')
    @app.get('/food')
    async def food():  return FileResponse(STATIC/'food.html')
    @app.get('/bi')
    async def bi():    return FileResponse(STATIC/'bi.html')

if DIST.exists():
    app.mount('/assets', StaticFiles(directory=str(DIST/'assets')), name='assets')

    @app.get('/{full_path:path}')
    async def spa(full_path: str):
        # Never intercept API routes
        if full_path.startswith('api/'):
            from fastapi.responses import JSONResponse
            return JSONResponse({'error': 'not found'}, status_code=404)
        f = DIST / full_path
        return FileResponse(f) if f.exists() and f.is_file() else FileResponse(DIST/'index.html')
else:
    @app.get('/')
    async def root(): return {'status': 'building'}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=PORT, log_level='warning')
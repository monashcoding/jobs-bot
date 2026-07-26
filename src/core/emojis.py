"""Discord emoji constants. Import and use directly in f-strings via str().

Usage:
    from src.core.emojis import KARMA_UP
    await message.reply(f"{KARMA_UP} +3 karma!")

To find an emoji ID, type \\:emoji_name: in Discord.
"""

from discord import PartialEmoji


def _emoji(emoji_id: int, name: str = "_", animated: bool = False) -> PartialEmoji:
    return PartialEmoji(name=name, id=emoji_id, animated=animated)


MAC_EMPLOYED = _emoji(1530617927198576743, "mac_employed")

GOOGLE = _emoji(1530618405156294726, "company_google")
TIKTOK = _emoji(1530620853291581620, "company_tiktok")
CANVA = _emoji(1530621095701385307, "company_canva")
ATLASSIAN = _emoji(1530621233237069945, "company_atlassian")
MONGODB = _emoji(1530621419317231776, "company_mongodb")
APPLE = _emoji(1530622765235703808, "company_apple")
STRIPE = _emoji(1530622948636098672, "company_stripe")
PALANTIR = _emoji(1530623101422010468, "company_palantir")
ARISTA = _emoji(1530623318250488049, "company_arista")
MICROSOFT = _emoji(1530623828722716732, "company_microsoft")
AMAZON = _emoji(1530624000798232787, "company_amazon")
SQUARE = _emoji(1530624298111336560, "company_square")
SNAP = _emoji(1530624542328754196, "company_snap")  # Snapchat
THE_TRADE_DESK = _emoji(1530624745660223712, "company_the_trade_desk")
SPOTIFY = _emoji(1530624926866870384, "company_spotify")
ROKT = _emoji(1530625142567338186, "company_rokt")
AIRWALLEX = _emoji(1530625315460612106, "company_airwallex")

XERO = _emoji(1530625747511935076, "company_xero")
TYRO = _emoji(1530625989493919884, "company_tyro")
CULTURE_AMP = _emoji(1530626138332729485, "company_culture_amp")
MACQUARIE_GROUP = _emoji(1530626736524497046, "company_macquarie_group")
COMMBANK = _emoji(1530626138332729485, "company_commbank")  # TODO: fix emoji ID
GOLDMAN_SACHS = _emoji(1530626987188813958, "company_goldman_sachs")
BANK_OF_AMERICA = _emoji(1530627174137204806, "company_bank_of_america")
LUXURY_ESCAPES = _emoji(1530627491654537216, "company_luxury_escapes")
DOVETAIL = _emoji(1530627904038375524, "company_dovetail")
EXPEDIA = _emoji(1530628097047789788, "company_expedia")
APPIAN = _emoji(1530628319203295354, "company_appian")
RELEVANCE_AI = _emoji(1530628486710952016, "company_relevance_ai")
AMD = _emoji(1530628718610092263, "company_amd")
ORACLE = _emoji(1530628905768190127, "company_oracle")
SALESFORCE = _emoji(1530629059585904802, "company_salesforce")
DOLBY = _emoji(1530629269519077586, "company_dolby")
ADOBE = _emoji(1530629392508649574, "company_adobe")
DRONESHIELD = _emoji(1530629557223162006, "company_droneshield")

CISCO = _emoji(1530777407835996281, "company_cisco")
SPORTSBET = _emoji(1530777604586475530, "company_sportsbet")
QUANTIUM = _emoji(1530777902772125856, "company_quantium")
GITLAB = _emoji(1530778116476375130, "company_gitlab")
COLES = _emoji(1530778282486927593, "company_coles")
WOOLWORTHS = _emoji(1530778449801777302, "company_woolworths")
EUCALYPTUS = _emoji(1530778618278707231, "company_eucalyptus")
HONEYWELL = _emoji(1530778806678454312, "company_honeywell")
ZENDESK = _emoji(1530778998919921675, "company_zendesk")
VGW = _emoji(1530779140347920535, "company_vgw")
LEIDOS = _emoji(1530779312427503646, "company_leidos")
CARSALES = _emoji(1530779419772194826, "company_carsales")
SEEK = _emoji(1530779554887499808, "company_seek")
REA = _emoji(1530779710005706783, "company_rea")
EASYGO = _emoji(1530779850384605347, "company_easygo")
LINKTREE = _emoji(1530780071139348641, "company_linktree")
AUSSUPER = _emoji(1530780332985552998, "company_aussuper")
REECETECH = _emoji(1530780524690280528, "company_reecetech")

FREELANCER = _emoji(1530780740588015636, "company_freelancer")
OPTUS = _emoji(1530780854488400024, "company_optus")
SLALOM = _emoji(1530781012903202826, "company_slalom")
MYOB = _emoji(1530781233624121454, "company_myob")
LEAP_DEV = _emoji(1530781378306904105, "company_leap_dev")
NINE = _emoji(1530781524897824849, "company_nine")  # Channel Nine
NAB = _emoji(1530781656187801733, "company_nab")
ANZ = _emoji(1530781819488960693, "company_anz")
DOMAIN = _emoji(1530781942939652296, "company_domain")
ADF = _emoji(1530782092579831918, "company_adf")
MEDIBANK = _emoji(1530782225103192094, "company_medibank")
RESMED = _emoji(1530782380225466368, "company_resmed")
COCHLEAR = _emoji(1530782500035756052, "company_cochlear")
WESTPAC = _emoji(1530782635918495846, "company_westpac")
SERVICE_NSW = _emoji(1530782782928978000, "company_service_nsw")
TELSTRA = _emoji(1530782905549459519, "company_telstra")

EY = _emoji(1530783088324640861, "company_ey")
DELOITTE = _emoji(1530783211746234458, "company_deloitte")
PWC = _emoji(1530783341404618913, "company_pwc")
KPMG = _emoji(1530783476524122242, "company_kpmg")
ACCENTURE = _emoji(1530783619977707572, "company_accenture")
THOUGHTWORKS = _emoji(1530783776865783871, "company_thoughtworks")
NRI = _emoji(1530783901402792136, "company_nri")
DXC = _emoji(1530784058035146864, "company_dxc")
WIPRO = _emoji(1530784225387741254, "company_wipro")
INFOSYS = _emoji(1530784406174961816, "company_infosys")
TCS = _emoji(1530784530686804028, "company_tcs")
COGNIZANT = _emoji(1530784625855692986, "company_cognizant")
HCL = _emoji(1530784808219836536, "company_hcl")
FDM_GROUP = _emoji(1530785000579141722, "company_fdm_group")
LYRA = _emoji(1530785572518367372, "company_lyra")

JUMP_TRADING = _emoji(1530621648703848749, "company_jump_trading")
JANE_STREET = _emoji(1530618919285555392, "company_jane_street")
CITADEL = _emoji(1530619200832540905, "company_citadel")
IMC = _emoji(1530619449974067342, "company_imc")
OPTIVER = _emoji(1530619803025408152, "company_optiver")
QRT = _emoji(1530620142264910105, "company_qrt")
HUDSON_RIVER_TRADING = _emoji(1530620292467261490, "company_hudson_river_trading")
TWO_SIGMA = _emoji(1530620661343588404, "company_two_sigma")
SIG = _emoji(1530621964098732122, "company_sig")  # Susquehanna
VIVCOURT_TRADING = _emoji(1530622216100778036, "company_vivcourt_trading")
AKUNA_CAPITAL = _emoji(1530622455436284133, "company_akuna_capital")

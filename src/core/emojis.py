"""Discord emoji constants. Import and use directly in f-strings via str().

Usage:
    from src.core.emojis import KARMA_UP
    await message.reply(f"{KARMA_UP} +3 karma!")

To find an emoji ID, type \\:emoji_name: in Discord.
"""

from typing import Final

from discord import PartialEmoji


def _emoji(emoji_id: int, name: str = "_", animated: bool = False) -> PartialEmoji:
    return PartialEmoji(name=name, id=emoji_id, animated=animated)


MAC_EMPLOYED: Final = _emoji(1530617927198576743, "mac_employed")

GOOGLE: Final = _emoji(1530618405156294726, "company_google")
TIKTOK: Final = _emoji(1530620853291581620, "company_tiktok")
CANVA: Final = _emoji(1530621095701385307, "company_canva")
ATLASSIAN: Final = _emoji(1530621233237069945, "company_atlassian")
MONGODB: Final = _emoji(1530621419317231776, "company_mongodb")
APPLE: Final = _emoji(1530622765235703808, "company_apple")
STRIPE: Final = _emoji(1530622948636098672, "company_stripe")
PALANTIR: Final = _emoji(1530623101422010468, "company_palantir")
ARISTA: Final = _emoji(1530623318250488049, "company_arista")
MICROSOFT: Final = _emoji(1530623828722716732, "company_microsoft")
AMAZON: Final = _emoji(1530624000798232787, "company_amazon")
SQUARE: Final = _emoji(1530624298111336560, "company_square")
SNAP: Final = _emoji(1530624542328754196, "company_snap")  # Snapchat
THE_TRADE_DESK: Final = _emoji(1530624745660223712, "company_the_trade_desk")
SPOTIFY: Final = _emoji(1530624926866870384, "company_spotify")
ROKT: Final = _emoji(1530625142567338186, "company_rokt")
AIRWALLEX: Final = _emoji(1530625315460612106, "company_airwallex")

XERO: Final = _emoji(1530625747511935076, "company_xero")
TYRO: Final = _emoji(1530625989493919884, "company_tyro")
CULTURE_AMP: Final = _emoji(1530626138332729485, "company_culture_amp")
MACQUARIE_GROUP: Final = _emoji(1530626736524497046, "company_macquarie_group")
COMMBANK: Final = _emoji(1530626412678090752, "company_commbank")
GOLDMAN_SACHS: Final = _emoji(1530626987188813958, "company_goldman_sachs")
BANK_OF_AMERICA: Final = _emoji(1530627174137204806, "company_bank_of_america")
LUXURY_ESCAPES: Final = _emoji(1530627491654537216, "company_luxury_escapes")
DOVETAIL: Final = _emoji(1530627904038375524, "company_dovetail")
EXPEDIA: Final = _emoji(1530628097047789788, "company_expedia")
APPIAN: Final = _emoji(1530628319203295354, "company_appian")
RELEVANCE_AI: Final = _emoji(1530628486710952016, "company_relevance_ai")
AMD: Final = _emoji(1530628718610092263, "company_amd")
ORACLE: Final = _emoji(1530628905768190127, "company_oracle")
SALESFORCE: Final = _emoji(1530629059585904802, "company_salesforce")
DOLBY: Final = _emoji(1530629269519077586, "company_dolby")
ADOBE: Final = _emoji(1530629392508649574, "company_adobe")
DRONESHIELD: Final = _emoji(1530629557223162006, "company_droneshield")

CISCO: Final = _emoji(1530777407835996281, "company_cisco")
SPORTSBET: Final = _emoji(1530777604586475530, "company_sportsbet")
QUANTIUM: Final = _emoji(1530777902772125856, "company_quantium")
GITLAB: Final = _emoji(1530778116476375130, "company_gitlab")
COLES: Final = _emoji(1530778282486927593, "company_coles")
WOOLWORTHS: Final = _emoji(1530778449801777302, "company_woolworths")
EUCALYPTUS: Final = _emoji(1530778618278707231, "company_eucalyptus")
HONEYWELL: Final = _emoji(1530778806678454312, "company_honeywell")
ZENDESK: Final = _emoji(1530778998919921675, "company_zendesk")
VGW: Final = _emoji(1530779140347920535, "company_vgw")
LEIDOS: Final = _emoji(1530779312427503646, "company_leidos")
CARSALES: Final = _emoji(1530779419772194826, "company_carsales")
SEEK: Final = _emoji(1530779554887499808, "company_seek")
REA: Final = _emoji(1530779710005706783, "company_rea")
EASYGO: Final = _emoji(1530779850384605347, "company_easygo")
LINKTREE: Final = _emoji(1530780071139348641, "company_linktree")
AUSSUPER: Final = _emoji(1530780332985552998, "company_aussuper")
REECETECH: Final = _emoji(1530780524690280528, "company_reecetech")

FREELANCER: Final = _emoji(1530780740588015636, "company_freelancer")
OPTUS: Final = _emoji(1530780854488400024, "company_optus")
SLALOM: Final = _emoji(1530781012903202826, "company_slalom")
MYOB: Final = _emoji(1530781233624121454, "company_myob")
LEAP_DEV: Final = _emoji(1530781378306904105, "company_leap_dev")
NINE: Final = _emoji(1530781524897824849, "company_nine")  # Channel Nine
NAB: Final = _emoji(1530781656187801733, "company_nab")
ANZ: Final = _emoji(1530781819488960693, "company_anz")
DOMAIN: Final = _emoji(1530781942939652296, "company_domain")
ADF: Final = _emoji(1530782092579831918, "company_adf")
MEDIBANK: Final = _emoji(1530782225103192094, "company_medibank")
RESMED: Final = _emoji(1530782380225466368, "company_resmed")
COCHLEAR: Final = _emoji(1530782500035756052, "company_cochlear")
WESTPAC: Final = _emoji(1530782635918495846, "company_westpac")
SERVICE_NSW: Final = _emoji(1530782782928978000, "company_service_nsw")
TELSTRA: Final = _emoji(1530782905549459519, "company_telstra")
MASTERCARD: Final = _emoji(1530627734684962886, "company_mastercard")

EY: Final = _emoji(1530783088324640861, "company_ey")
DELOITTE: Final = _emoji(1530783211746234458, "company_deloitte")
PWC: Final = _emoji(1530783341404618913, "company_pwc")
KPMG: Final = _emoji(1530783476524122242, "company_kpmg")
ACCENTURE: Final = _emoji(1530783619977707572, "company_accenture")
THOUGHTWORKS: Final = _emoji(1530783776865783871, "company_thoughtworks")
NRI: Final = _emoji(1530783901402792136, "company_nri")
DXC: Final = _emoji(1530784058035146864, "company_dxc")
WIPRO: Final = _emoji(1530784225387741254, "company_wipro")
INFOSYS: Final = _emoji(1530784406174961816, "company_infosys")
TCS: Final = _emoji(1530784530686804028, "company_tcs")
COGNIZANT: Final = _emoji(1530784625855692986, "company_cognizant")
HCL: Final = _emoji(1530784808219836536, "company_hcl")
FDM_GROUP: Final = _emoji(1530785000579141722, "company_fdm_group")
LYRA: Final = _emoji(1530785572518367372, "company_lyra")

JUMP_TRADING: Final = _emoji(1530621648703848749, "company_jump_trading")
JANE_STREET: Final = _emoji(1530618919285555392, "company_jane_street")
CITADEL: Final = _emoji(1530619200832540905, "company_citadel")
IMC: Final = _emoji(1530619449974067342, "company_imc")
OPTIVER: Final = _emoji(1530619803025408152, "company_optiver")
QRT: Final = _emoji(1530620142264910105, "company_qrt")
HUDSON_RIVER_TRADING: Final = _emoji(
    1530620292467261490, "company_hudson_river_trading"
)
TWO_SIGMA: Final = _emoji(1530620661343588404, "company_two_sigma")
SIG: Final = _emoji(1530621964098732122, "company_sig")  # Susquehanna
VIVCOURT_TRADING: Final = _emoji(1530622216100778036, "company_vivcourt_trading")
AKUNA_CAPITAL: Final = _emoji(1530622455436284133, "company_akuna_capital")

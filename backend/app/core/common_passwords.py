"""Common-password blocklist (base words, lowercase, no trailing digits or
symbols). validators.validate_password lowercases the candidate, strips trailing
digits/symbols and rejects it if the result is one of these - so "Password1!",
"PASSWORD123#" and "pAssw0rd" style variants are all caught by a single entry.
"""

COMMON_BASE_WORDS: frozenset[str] = frozenset("""
password passw0rd passwd pass pwd secret letmein welcome admin administrator root
user guest login master qwerty qwertyuiop qwert asdf asdfgh asdfghjkl zxcv zxcvbn
zxcvbnm azerty abc abcd abcde abcdef abcdefg abc xyz iloveyou ilove love lovely
sunshine princess dragon monkey shadow football baseball basketball soccer hockey
cricket tennis golf superman batman spiderman ironman hulk avengers pokemon naruto
starwars trustno trustno1 whatever freedom michael jordan jennifer jessica ashley
nicole daniel thomas robert charlie andrew matthew joshua hunter harley ranger
buster butter summer winter spring autumn monday tuesday friday sunday january
february march april june july august september october november december
india indian delhi mumbai bombay kolkata chennai bangalore hyderabad ahmedabad
gujarat rajasthan kerala punjab bharat jaihind krishna ganesh shiva shivam ram
hanuman om namaste sai saibaba radha raja rani babu guddu pappu golu monu sonu
cool hello hellohello hi hey test testing tester test123 temp temporary demo sample
default changeme change me myself mypass mypassword mypasswd pass123 passw
newpass newpassword newuser oldpass access system server network computer laptop
internet google gmail yahoo hotmail outlook facebook instagram whatsapp twitter
youtube amazon flipkart paytm company office work home house family mother father
sister brother friend friends happy lucky money cash rich gold silver diamond
tiger lion eagle wolf bear cat dog puppy kitten banana apple orange cherry cookie
chocolate coffee pepper ginger killer hacker cracker ninja pirate wizard magic
matrix phoenix thunder lightning rocket mustang ferrari porsche corvette camaro
toyota honda yamaha suzuki bajaj tata mahindra maruti hero reliance oerlikon
ackintel ackn acknowledgement invoice challan delivery transport bill bills
""".split())

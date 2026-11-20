from . import brightermonday, fuzu, myjobmag, remotive, remoteok, whatsapp

# Registry: name -> fetch function. Add new sources here.
SOURCES = {
    "myjobmag": myjobmag.fetch,
    "brightermonday": brightermonday.fetch,
    "fuzu": fuzu.fetch,
    "remotive": remotive.fetch,
    "remoteok": remoteok.fetch,
    "whatsapp": whatsapp.fetch,
}

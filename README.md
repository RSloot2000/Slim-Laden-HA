# Peblar Slim Laden

*[Nederlands](#nederlands) · [English](#english)*

---

## Nederlands

> **Persoonlijke integratie.** Deze Home Assistant-integratie is uitsluitend
> gemaakt voor mijn eigen opstelling. Ze is niet bedoeld, getest of ondersteund
> voor gebruik door anderen en werkt vrijwel zeker niet zonder aanpassing in een
> andere setup. Gebruik op eigen risico.

De integratie regelt het laden van een elektrische auto op een Peblar-laadpaal:
ze volgt het PV-overschot, spreidt wat er van het net bij moet over de nacht en
zorgt dat de auto op de ingestelde vertrektijd op zijn doel-SoC staat. Verder
leert ze uit de eigen meetgegevens onder meer het werkelijke laadrendement, het
huisverbruik per weekdag en uur, en de betrouwbaarheid van de zonvoorspelling.

### Gebruik door anderen

Deze repository staat onder de [Unlicense](LICENSE) en is daarmee vrijgegeven
aan het publieke domein. Het staat iedereen vrij de code of de ideeën over te
nemen, aan te passen en te verspreiden, voor welk doel dan ook. Vermelding is
niet nodig en er zit geen enkele verplichting aan vast.

Wat je er níét bij krijgt: ondersteuning, garantie of enige aansprakelijkheid.
De regellogica stuurt echte apparatuur aan en gaat uit van mijn hardware, mijn
sensoren en mijn netaansluiting. Neem het dus niet blind over, maar lees het
door en pas het aan op je eigen situatie.

---

## English

> **Personal integration.** This Home Assistant integration was built solely for
> my own setup. It is not intended, tested or supported for use by anyone else
> and almost certainly will not work in a different setup without changes. Use
> at your own risk.

The integration controls EV charging on a Peblar charger: it follows the solar
surplus, spreads whatever still has to come from the grid across the night, and
makes sure the car reaches its target state of charge by the configured
departure time. It also learns from its own measurements, including the actual
charging efficiency, household consumption per weekday and hour, and how
accurate the solar forecast turns out to be.

### Use by others

This repository is released into the public domain under the
[Unlicense](LICENSE). Anyone is free to take the code or the ideas, adapt them
and redistribute them, for any purpose whatsoever. No attribution is required
and no strings are attached.

What you do not get: support, warranty or any liability on my part. This logic
drives real hardware and assumes my charger, my sensors and my grid connection.
So please do not copy it blindly — read it and adapt it to your own situation.

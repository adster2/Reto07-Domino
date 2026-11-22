"""English presentation of errors from the unchanged camera modules."""
def english_error(message):
    text = str(message)
    replacements = {
        'Camo trovata ma non apribile: controllare altre applicazioni video.': 'Camo was found but cannot be opened: check other video applications.',
        'Acquisizione interrotta: dieci letture senza fotogramma.': 'Capture interrupted: ten reads returned no frame.',
        'Nessun fotogramma da Camo entro 10 secondi.': 'Camo did not provide a frame within 10 seconds.',
        'Flusso bloccato: nessun nuovo fotogramma da 10 secondi.': 'Video stream frozen: no new frame for 10 seconds.',
        'Sorgente ': 'Source ',
        ' assente o ambigua. Disponibili: ': ' is missing or ambiguous. Available: ',
        'Salvataggio fallito: ': 'Save failed: ',
    }
    for original, translated in replacements.items():
        text = text.replace(original, translated)
    return text

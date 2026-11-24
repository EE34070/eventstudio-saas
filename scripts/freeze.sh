#!/bin/sh
# Met à jour backend/requirements.txt sans figer litellm (dépendance d'emergentintegrations, sinon ResolutionImpossible).
cd "$(dirname "$0")/../backend" && pip freeze | grep -vi '^litellm' > requirements.txt

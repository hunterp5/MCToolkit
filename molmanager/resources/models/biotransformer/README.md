# BioTransformer 3.0 (optional, not in git)

**Source:** Djoumbou Feunang et al., *BioTransformer: A Comprehensive Computational Tool for Small Molecule Metabolism Prediction and Metabolite Identification*, J. Cheminform. 2019.  
https://doi.org/10.1186/s13321-018-0324-5

**License:** GNU LGPL v3. Commercial redistribution of BioTransformer resources needs explicit permission from the authors.

Place these files in **this directory** (or point `MOLMANAGER_BIOTRANSFORMER_JAR` at the JAR; `database/` and `supportfiles/` must sit next to that JAR):

```
biotransformer-3.0.0.jar
database/
supportfiles/
```

Download the runnable JAR and support folders from:

- https://github.com/Wishartlab-openscience/Biotransformer
- https://bitbucket.org/wishartlab/biotransformer3.0jar

**Java** must be on `PATH` (`java -version`). Official docs target UNIX; on native Windows, try a current JRE first. If the JAR fails, run BioTransformer under WSL and point `MOLMANAGER_BIOTRANSFORMER_JAR` at that install.

Do not enable PubChem annotate (`-a`) from MolManager. The environmental microbial module is not offered in v1 (EnviPath non-commercial terms).

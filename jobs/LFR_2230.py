import sys
sys.path.append(r"C:\radio-podcast")
import pipeline

pipeline.CONFIG["station"] = "LFR"
pipeline.CONFIG["duration"] = 1830
pipeline.CONFIG["auto_git_push"] = True
pipeline.main()
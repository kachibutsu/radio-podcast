import sys
sys.path.append(r"C:\radio-podcast")
import pipeline

pipeline.CONFIG["station"] = "TBS"
pipeline.CONFIG["duration"] = 7230
pipeline.CONFIG["auto_git_push"] = True
pipeline.main()
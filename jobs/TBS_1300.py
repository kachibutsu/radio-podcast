import sys
sys.path.append(r"C:\radio-podcast")
import pipeline

pipeline.CONFIG["station"] = "TBS"
pipeline.CONFIG["duration"] = 14430
pipeline.CONFIG["auto_git_push"] = True
pipeline.CONFIG["program_name"] = "日曜サンデー"
pipeline.main()
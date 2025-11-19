# BCApps Dataset

# 📦 BCApps Dataset

This folder is primarily used to retrieve datasets from the **BCApps** project:
[https://github.com/microsoft/BCApps](https://github.com/microsoft/BCApps)

You are welcome to modify and use the contents as needed.
The recommended usage flow is:

---

## 🔧 Usage Workflow

### **1. Clone or download this repository (or this folder)**

You may clone the entire project or copy only the dataset-related scripts.

### **2. Extract or retrieve the required datasets**

Run the following scripts with a specific Pull Request ID:

```bash
python simple_fetch.py <PR_id>
python convert_diff.py <PR_id>
python process_pr_commits.py <PR_id>
python process_comments.py <PR_id>
```

### **3. Use the output datasets**

The processed data can then be used in your further analysis or downstream pipelines.

---


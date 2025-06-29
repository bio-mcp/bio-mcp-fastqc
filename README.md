# Bio-MCP FastQC Server 🔬

**Quality Control Analysis via Model Context Protocol**

An MCP server that enables AI assistants to run FastQC and MultiQC quality control analysis on sequencing data. Part of the [Bio-MCP ecosystem](https://github.com/bio-mcp).

## 🎯 Purpose

FastQC is essential for quality assessment of high-throughput sequencing data. This MCP server allows AI assistants to:

- **Analyze single files** - Get detailed QC reports for individual FASTQ/FASTA files
- **Batch process** - Run QC on multiple files simultaneously  
- **Generate summary reports** - Create MultiQC reports combining multiple analyses
- **Handle large datasets** - Queue system support for computationally intensive jobs

## 🚀 Quick Start

### Prerequisites

Install FastQC and MultiQC:

```bash
# Via conda (recommended)
conda install -c bioconda fastqc multiqc

# Via package managers
# Ubuntu/Debian
sudo apt-get install fastqc
pip install multiqc

# macOS
brew install fastqc
pip install multiqc
```

### Installation

```bash
# Clone and install
git clone https://github.com/bio-mcp/bio-mcp-fastqc.git
cd bio-mcp-fastqc
pip install -e .

# Or install directly
pip install git+https://github.com/bio-mcp/bio-mcp-fastqc.git
```

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "bio-fastqc": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/bio-mcp-fastqc"
    }
  }
}
```

## 🔧 Available Tools

### Core Analysis Tools

#### `fastqc_single`
Run FastQC on a single FASTQ/FASTA file.

**Parameters:**
- `input_file` (required): Path to FASTQ or FASTA file
- `threads` (optional): Number of threads (default: 1)
- `contaminants` (optional): Path to custom contaminants file
- `adapters` (optional): Path to custom adapters file
- `limits` (optional): Path to custom limits file

**Example:**
```
User: "Run quality control on my_sample.fastq.gz"
AI: [calls fastqc_single] → Returns detailed QC report with pass/warn/fail status for each module
```

#### `fastqc_batch`
Run FastQC on multiple files in a directory.

**Parameters:**
- `input_dir` (required): Directory containing FASTQ/FASTA files
- `file_pattern` (optional): File pattern to match (default: "*.fastq*")
- `threads` (optional): Number of threads (default: 4)

**Example:**
```
User: "Analyze all fastq files in the data/ directory"
AI: [calls fastqc_batch] → Processes all files and returns summary statistics
```

#### `multiqc_report`
Generate MultiQC report from FastQC results.

**Parameters:**
- `input_dir` (required): Directory containing FastQC and other analysis results
- `title` (optional): Custom title for the report
- `comment` (optional): Comment to add to the report
- `template` (optional): Report template (default, simple, sections, gathered)

**Example:**
```
User: "Create a summary report from all the QC results"
AI: [calls multiqc_report] → Generates interactive HTML report combining all analyses
```

### Queue System Tools (when queue enabled)

For large datasets or batch processing:

- `fastqc_single_async` - Queue single file analysis
- `fastqc_batch_async` - Queue batch analysis
- `multiqc_report_async` - Queue report generation
- `get_job_status` - Check job progress
- `get_job_result` - Retrieve completed results
- `cancel_job` - Cancel running jobs

## 💡 Usage Examples

### Basic Quality Assessment

```
User: "What's the quality of my sequencing data in sample1.fastq.gz?"

AI Response:
✅ FastQC Analysis Complete for sample1

Module Status Summary:
✅ Basic Statistics: PASS
✅ Per base sequence quality: PASS
⚠️ Per sequence quality scores: WARN
✅ Per base sequence content: PASS
✅ Per sequence GC content: PASS
✅ Per base N content: PASS
✅ Sequence Length Distribution: PASS
❌ Sequence Duplication Levels: FAIL
✅ Overrepresented sequences: PASS
✅ Adapter Content: PASS

Basic Statistics:
• Total Sequences: 2,450,000
• Sequences flagged as poor quality: 0
• Sequence length: 150
• %GC: 47
```

### Batch Analysis

```
User: "Analyze all FASTQ files in my project/raw_data/ folder"

AI Response:
FastQC Batch Analysis Complete
========================================

Processed 12 files:

✅ sample01_R1.fastq.gz: 8P/2W/0F
✅ sample01_R2.fastq.gz: 8P/2W/0F
⚠️ sample02_R1.fastq.gz: 7P/2W/1F
⚠️ sample02_R2.fastq.gz: 7P/2W/1F
...

Overall Summary:
• Total PASS: 94
• Total WARN: 24
• Total FAIL: 2

Tip: Run multiqc_report on this directory to generate a combined report!
```

### Complete Workflow

```
User: "I have a directory of paired-end FASTQ files. Can you run quality control and create a summary report?"

AI: I'll run a complete QC workflow on your paired-end data:

1. First, let me analyze all FASTQ files in batch:
   [runs fastqc_batch on directory]

2. Now I'll generate a MultiQC summary report:
   [runs multiqc_report on results]

✅ Complete QC workflow finished!

Summary:
- 24 FASTQ files processed (12 samples, paired-end)
- Average quality score: 32.5
- 2 samples have adapter contamination warnings
- 1 sample shows high duplication levels
- Interactive HTML report generated: multiqc_report.html

The MultiQC report provides detailed visualizations of:
- Quality score distributions across all samples
- GC content comparison
- Sequence length distributions
- Adapter content analysis
- Sample correlation analysis
```

## 🐳 Docker Usage

### Build and Run

```bash
# Build the image
docker build -t bio-mcp-fastqc .

# Run with data mounting
docker run -v /path/to/data:/data bio-mcp-fastqc
```

### Docker Compose (with Queue System)

```yaml
services:
  fastqc-server:
    build: .
    volumes:
      - ./data:/data
    environment:
      - BIO_MCP_QUEUE_URL=http://queue-api:8000
    depends_on:
      - queue-api
```

## ⚙️ Configuration

### Environment Variables

- `BIO_MCP_FASTQC_PATH` - Path to FastQC executable (default: "fastqc")
- `BIO_MCP_MULTIQC_PATH` - Path to MultiQC executable (default: "multiqc")
- `BIO_MCP_MAX_FILE_SIZE` - Maximum file size in bytes (default: 10GB)
- `BIO_MCP_TIMEOUT` - Command timeout in seconds (default: 1800)
- `BIO_MCP_TEMP_DIR` - Temporary directory for processing

### Queue System Integration

To enable async processing for large datasets:

```python
from src.server_with_queue import FastQCServerWithQueue

server = FastQCServerWithQueue(queue_url="http://localhost:8000")
```

## 📊 Output Files

FastQC generates several output files:

- **HTML Report** (`*_fastqc.html`) - Interactive quality report
- **Data File** (`fastqc_data.txt`) - Raw metrics and statistics  
- **Summary File** (`summary.txt`) - Pass/warn/fail status for each module
- **Plots** - Various quality plots and charts

MultiQC combines these into:

- **MultiQC Report** (`multiqc_report.html`) - Combined interactive report
- **Data Directory** (`multiqc_data/`) - Processed data and statistics
- **General Stats** (`multiqc_general_stats.txt`) - Summary table

## 🔍 Quality Metrics Explained

FastQC analyzes multiple quality aspects:

### Key Modules
- **Per base sequence quality** - Quality scores across read positions
- **Per sequence quality scores** - Distribution of mean quality scores
- **Per base sequence content** - A/T/G/C content across positions
- **Per sequence GC content** - GC% distribution vs expected
- **Sequence duplication levels** - PCR duplication assessment
- **Adapter content** - Contaminating adapter sequences

### Status Interpretation
- ✅ **PASS** - Analysis indicates no problems
- ⚠️ **WARN** - Slightly unusual, may not be problematic
- ❌ **FAIL** - Likely problematic, requires attention

## 🧬 Integration with Bio-MCP Ecosystem

FastQC works seamlessly with other Bio-MCP tools:

```
User: "Run the complete preprocessing pipeline on my samples"

AI Workflow:
1. fastqc_batch → Initial quality assessment
2. trimmomatic → Trim low-quality bases and adapters  
3. fastqc_batch → Post-trimming QC
4. multiqc_report → Combined before/after report
```

## 🤝 Contributing

We welcome contributions! See the [Bio-MCP contributing guide](https://github.com/bio-mcp/.github/blob/main/CONTRIBUTING.md).

### Development Setup

```bash
git clone https://github.com/bio-mcp/bio-mcp-fastqc.git
cd bio-mcp-fastqc
pip install -e ".[dev]"
pytest
```

## 📄 License

MIT License - see [LICENSE](LICENSE) file.

## 🙏 Acknowledgments

- **FastQC** by Simon Andrews at Babraham Bioinformatics
- **MultiQC** by Phil Ewels and the MultiQC community
- **Bio-MCP** project and contributors

---

**Part of the Bio-MCP ecosystem** - Making bioinformatics accessible to AI assistants.

For more tools: [Bio-MCP Organization](https://github.com/bio-mcp)
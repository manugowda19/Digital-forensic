# ForensAI - Advanced Digital Forensics Platform

**Version:** 1.0.0  
**Author:** Manu
**License:** MIT  

## Overview

ForensAI is a modern, cost-effective digital forensics platform designed to overcome the limitations of traditional commercial tools like FTK (Forensic Toolkit). Built with Python and Flask, ForensAI provides investigators with an intuitive web-based interface for conducting comprehensive digital forensic analysis, including advanced file carving, real-time processing updates, and robust error handling.

The platform addresses key challenges in digital forensics by offering a resource-efficient solution that supports modern file systems, provides scripting capabilities for automation, and maintains stability and reliability throughout the investigation process. ForensAI is designed for continuous innovation to keep pace with evolving forensic needs while remaining accessible to organizations with varying budget constraints.

## Key Features

### Core Functionality
- **Advanced File Carving**: Comprehensive signature-based file recovery supporting 45+ file types across 12 categories
- **Real-time Processing**: Live progress updates via WebSocket connections for long-running operations
- **Modern Web Interface**: Responsive, intuitive dashboard accessible from any modern web browser
- **Multi-format Support**: Handles various evidence formats including disk images, memory dumps, and individual files

### Technical Capabilities
- **Robust Error Handling**: Comprehensive error management with automatic retry mechanisms and detailed logging
- **Database Integration**: SQLite-based evidence management with support for case organization and metadata storage
- **Multiprocessing Support**: Windows-safe background processing for resource-intensive operations
- **Extensible Architecture**: Modular design allowing for easy addition of new analysis modules

### Security and Reliability
- **User Authentication**: Secure login system with password hashing and session management
- **Input Validation**: Comprehensive validation of user inputs and uploaded files
- **Error Recovery**: Automatic retry mechanisms for transient failures
- **Audit Logging**: Detailed logging of all operations for forensic accountability

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Flask and related dependencies
- SQLite (included with Python)
- Modern web browser (Chrome, Firefox, Safari, Edge)

### Installation

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd forensai
   ```

2. **Install Dependencies**
   ```bash
   pip install flask flask-sqlalchemy flask-login flask-socketio flask-cors werkzeug
   ```

3. **Initialize Database**
   ```bash
   python init_db.py
   ```

4. **Run the Application**
   ```bash
   cd src
   python main.py
   ```

5. **Access the Interface**
   Open your web browser and navigate to `http://localhost:5000`

### Default Credentials

- **Username:** admin
- **Password:** admin123

*Note: Change these credentials immediately after first login in a production environment.*

## System Architecture

ForensAI follows a modular architecture designed for scalability and maintainability:

### Core Components

1. **Web Application Layer** (`src/main.py`)
   - Flask-based web server with SocketIO support
   - User authentication and session management
   - Route handling and request processing

2. **Data Models** (`src/models/`)
   - `case.py`: Case and evidence management
   - `user.py`: User authentication and authorization

3. **Processing Engine** (`src/forensics/`)
   - `processor.py`: Main processing coordinator
   - `carver.py`: File carving implementation

4. **Web Interface** (`src/routes/`)
   - `dashboard.py`: Main dashboard and statistics
   - `case.py`: Case management operations
   - `processing.py`: Evidence processing and carving

5. **Utilities** (`src/utils/`)
   - `error_handler.py`: Comprehensive error management

### Database Schema

The system uses SQLite with the following main entities:

- **Users**: Authentication and user management
- **Cases**: Investigation case organization
- **Evidence**: Evidence file tracking and metadata
- **EvidenceItems**: Individual evidence items within cases
- **AnalysisResults**: Results from various analysis operations

## File Carving Capabilities

ForensAI's file carving engine supports comprehensive file type detection and recovery:

### Supported File Categories

1. **Image Formats**: JPEG, PNG, GIF, BMP, TIFF, ICO, WebP
2. **Audio Formats**: MP3, WAV, OGG, FLAC, M4A
3. **Video Formats**: MP4, FLV, MKV, AVI
4. **Document Formats**: PDF, DOC, DOCX, RTF, XML, HTML
5. **Archive Formats**: ZIP, RAR, GZIP, BZIP2, 7-Zip, XZ
6. **Executable Formats**: ELF, Windows PE, Java Class, Mach-O
7. **Database Formats**: SQLite, Microsoft Access
8. **Font Formats**: TrueType, OpenType, WOFF
9. **CAD Formats**: AutoCAD DWG
10. **Email Formats**: EML, PST
11. **Registry Formats**: Windows Registry Hives
12. **Forensic Formats**: EnCase E01, Advanced Forensic Format

### Carving Features

- **Signature-based Detection**: Uses magic numbers for accurate file type identification
- **End Marker Validation**: Proper file boundary detection where applicable
- **Size Validation**: Configurable minimum and maximum file size limits
- **Category Filtering**: Ability to carve specific file types or categories
- **Progress Reporting**: Real-time progress updates during carving operations
- **Comprehensive Reporting**: Detailed reports with statistics and file listings

## Error Handling and Reliability

ForensAI implements a comprehensive error handling system designed to ensure reliability and provide meaningful feedback:

### Error Categories

1. **Database Errors**: Connection issues, constraint violations, transaction failures
2. **File Operation Errors**: Permission issues, disk space, corrupted files
3. **Processing Errors**: Memory limitations, timeout conditions, multiprocessing failures
4. **Validation Errors**: Invalid input data, malformed requests
5. **Authentication Errors**: Login failures, session timeouts

### Recovery Mechanisms

- **Automatic Retry**: Exponential backoff for transient failures
- **Graceful Degradation**: Fallback options when primary methods fail
- **Safe Cleanup**: Proper resource cleanup even during error conditions
- **Detailed Logging**: Comprehensive error logging for troubleshooting

## API Reference

ForensAI provides RESTful APIs for programmatic access:

### Authentication Endpoints

- `POST /login`: User authentication
- `GET /logout`: User logout

### Case Management

- `GET /api/cases`: List all cases
- `POST /api/cases`: Create new case
- `GET /api/cases/{id}`: Get case details
- `PUT /api/cases/{id}`: Update case
- `DELETE /api/cases/{id}`: Delete case

### Evidence Processing

- `POST /api/cases/{case_id}/evidence/{evidence_id}/analyze`: Start analysis
- `GET /api/cases/{case_id}/evidence/{evidence_id}/status`: Get processing status
- `GET /api/cases/{case_id}/evidence/{evidence_id}/results`: Get analysis results

### File Carving

- `POST /api/cases/{case_id}/carve`: Upload and carve evidence file
- `GET /api/cases/{case_id}/evidence/{evidence_id}/carving_results`: View carved files

### System Status

- `GET /api/health`: System health check
- `GET /api/dashboard/stats`: Dashboard statistics
- `GET /api/info`: System information

## Development Guide

### Adding New File Signatures

To add support for new file types in the carving engine:

1. **Update FILE_SIGNATURES** in `src/forensics/carver.py`:
   ```python
   b"\x50\x4B\x03\x04": {
       "ext": "zip", 
       "name": "ZIP archive", 
       "end": b"\x50\x4B\x05\x06", 
       "category": "archive"
   }
   ```

2. **Add Validation Logic** in `_validate_file_data()` method if needed

3. **Update Tests** to include the new file type

### Extending Analysis Capabilities

To add new analysis modules:

1. **Create Analysis Module** in `src/forensics/`
2. **Update Processor** to integrate the new module
3. **Add Database Models** for storing results
4. **Create API Endpoints** for accessing results
5. **Update Web Interface** to display results

## Testing and Validation

ForensAI includes a comprehensive test suite to validate system functionality:

### Running Tests

```bash
python test_system.py
```

### Test Coverage

The test suite validates:

- Database operations and user authentication
- File carving with various file types
- Error handling and recovery mechanisms
- Application startup and component initialization

### Continuous Integration

For production deployments, integrate the test suite into your CI/CD pipeline to ensure system reliability.

## Security Considerations

### Authentication and Authorization

- Secure password hashing using Werkzeug
- Session-based authentication with Flask-Login
- Input validation and sanitization
- CSRF protection for web forms

### Data Protection

- Secure file handling with proper permissions
- Temporary file cleanup after processing
- Database encryption for sensitive data (recommended for production)
- Audit logging for accountability

### Network Security

- HTTPS support (configure reverse proxy)
- CORS configuration for API access
- Rate limiting for API endpoints (recommended)
- Firewall configuration for production deployment

## Performance Optimization

### System Requirements

- **Minimum**: 4GB RAM, 2 CPU cores, 10GB storage
- **Recommended**: 16GB RAM, 8 CPU cores, 100GB+ storage
- **Large Cases**: 32GB+ RAM, 16+ CPU cores, 1TB+ storage

### Optimization Tips

1. **Memory Management**: Configure appropriate file size limits for carving
2. **Disk I/O**: Use SSD storage for better performance
3. **Multiprocessing**: Adjust worker processes based on CPU cores
4. **Database**: Regular maintenance and indexing for large datasets

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Verify database file permissions
   - Check SQLite installation
   - Review database URI configuration

2. **File Carving Failures**
   - Verify input file accessibility
   - Check available disk space
   - Review file size limits

3. **Authentication Problems**
   - Reset admin password using init_db.py
   - Check session configuration
   - Verify user database entries

### Log Analysis

ForensAI generates detailed logs in `forensai_errors.log`. Review this file for:
- Error patterns and frequencies
- Performance bottlenecks
- Security incidents
- System health indicators

## Contributing

We welcome contributions to ForensAI! Please follow these guidelines:

1. **Code Style**: Follow PEP 8 Python style guidelines
2. **Testing**: Add tests for new functionality
3. **Documentation**: Update documentation for changes
4. **Error Handling**: Implement proper error handling
5. **Security**: Consider security implications of changes

## License

ForensAI is released under the MIT License. See LICENSE file for details.

## Support and Contact

For technical support, bug reports, or feature requests:

- **Documentation**: This README and inline code comments
- **Testing**: Run `python test_system.py` for system validation
- **Issues**: Review error logs and system health endpoints

## Changelog

### Version 1.0.0
- Initial release with core forensic capabilities
- Advanced file carving with 45+ file type support
- Real-time processing with WebSocket updates
- Comprehensive error handling and recovery
- Web-based dashboard and case management
- User authentication and session management
- SQLite database integration
- Multiprocessing support for background tasks
- Extensive test suite and validation framework


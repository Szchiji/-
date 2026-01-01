class CustomEditor {
    constructor(containerId, initialContent) {
        this.container = document.getElementById(containerId);
        this.textarea = document.createElement('textarea');
        this.textarea.style.display = 'none';
        this.container.appendChild(this.textarea);

        // 工具栏 (仿截图1)
        this.toolbar = document.createElement('div');
        this.toolbar.className = 'editor-tb btn-group mb-2';
        this.container.appendChild(this.toolbar);

        // 编辑区
        this.editor = document.createElement('div');
        this.editor.className = 'form-control editor-content';
        this.editor.contentEditable = true;
        this.editor.style.minHeight = '150px';
        this.editor.innerHTML = initialContent || '';
        this.container.appendChild(this.editor);

        this.initTools();
        
        // 绑定事件
        this.editor.addEventListener('input', () => this.textarea.value = this.editor.innerHTML);
    }
    
    initTools() {
        const tools = [
            {icon: 'B', cmd: 'bold'}, 
            {icon: 'I', cmd: 'italic'},
            {icon: '🔗', cmd: 'createLink', prompt: true}
        ];
        tools.forEach(t => {
            const btn = document.createElement('button');
            btn.innerHTML = t.icon;
            btn.className = 'btn btn-light btn-sm border';
            btn.type = 'button';
            btn.onclick = () => {
                if(t.prompt) {
                    const url = prompt("URL:");
                    if(url) document.execCommand(t.cmd, false, url);
                } else {
                    document.execCommand(t.cmd, false, null);
                }
            };
            this.toolbar.appendChild(btn);
        });
    }
    
    insertVar(text) {
        this.editor.focus();
        document.execCommand('insertText', false, text);
        this.textarea.value = this.editor.innerHTML;
    }
    
    getValue() { return this.editor.innerHTML; }
}

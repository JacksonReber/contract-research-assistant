interface UserBubbleProps {
  text: string;
}

export function UserBubble({ text }: UserBubbleProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-blue-600 px-4 py-2 text-sm text-white">
        <div className="whitespace-pre-wrap">{text}</div>
      </div>
    </div>
  );
}
